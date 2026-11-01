"""
desk-presence MCP server (Windows)

DVDドライブのトレイを開き、人間が閉じたことをもって「デスクに人間がいる」と判定する。

【状態取得の仕組み】
  SCSI Pass-Through で TEST UNIT READY (CDB 00h x6) を発行し、sense データの
  ASC/ASCQ を読む。状態は DeviceIoControl の戻り値ではなく sense だけで決める。
    ASC 3Ah / ASCQ 02h : MEDIUM NOT PRESENT - TRAY OPEN
    ASC 3Ah / ASCQ 01h : MEDIUM NOT PRESENT - TRAY CLOSED
    ASC 04h            : LOGICAL UNIT NOT READY (開閉・認識の途中)
  ※ 実機試験(HL-DT-ST GH24NSD5 / Windows)では管理者権限なしで動作を確認。
    環境によって Access denied (5) になる場合のみ管理者で起動すること。

【イジェクト / クローズ】
  MCI (winmm) の `set <alias> door open|closed`。同期呼び出しで、トレイが
  動き終わるまで戻らない（本機で約2.8秒）。

【response_sec の起点】
  トレイが「開き切った」ことを確認した時点。コマンド発行時点からの値は
  response_since_command_sec。

【MCP SDK のバージョン】
  mcp 1.x (FastMCP) と mcp 2.x (MCPServer) の両方で動く。
    - 2.x: from mcp.server.mcpserver import MCPServer。host/port は run() に渡す
    - 1.x: from mcp.server.fastmcp import FastMCP。host/port はコンストラクタに渡す
  依存: pip install mcp   (Python 3.10+)

【起動】
  python desk_presence_server.py
  既定は Streamable HTTP (127.0.0.1:8765/mcp)。
    MCP_TRANSPORT=stdio        stdio で起動
    MCP_HOST / MCP_PORT        待ち受けアドレス (既定 127.0.0.1 / 8765)
    DVD_DRIVE=E:               ドライブ文字の固定
    PRESENCE_FAST_DETECT=1     「開いているはずのトレイでTURが1.5秒返らない
                               ＝ドライブ動作中」を閉じ操作の証拠として早期確定
                               （試験的・既定オフ）

【文字コード】
  クライアントに返る文字列（ツール説明・hint・note など）はエンコード不具合を
  避けるため英語にしてある。ソースは UTF-8 で保存すること（古いメモ帳の
  「ANSI」保存だとコメントの日本語で SyntaxError になる）。
"""
import asyncio
import ctypes
import os
import string
import time
from ctypes import wintypes
from typing import Annotated

from pydantic import Field

# --- MCP SDK の差異を吸収（2.x を先に試し、無ければ 1.x） ---------------------
try:
    from mcp.server.mcpserver import Context, MCPServer as _Server  # mcp 2.x
    MCP_V2 = True
except ImportError:
    from mcp.server.fastmcp import Context, FastMCP as _Server      # mcp 1.x
    MCP_V2 = False

# ---------------------------------------------------------------- Win32 定義
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
DRIVE_CDROM = 5
IOCTL_SCSI_PASS_THROUGH = 0x0004D004
SCSI_IOCTL_DATA_UNSPECIFIED = 2

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.DeviceIoControl.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
    wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
kernel32.DeviceIoControl.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


class SCSI_PASS_THROUGH(ctypes.Structure):
    # Windows の ULONG は 32bit。ULONG_PTR は c_size_t で表現(自然アライメントに任せる)
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("ScsiStatus", ctypes.c_ubyte),
        ("PathId", ctypes.c_ubyte),
        ("TargetId", ctypes.c_ubyte),
        ("Lun", ctypes.c_ubyte),
        ("CdbLength", ctypes.c_ubyte),
        ("SenseInfoLength", ctypes.c_ubyte),
        ("DataIn", ctypes.c_ubyte),
        ("DataTransferLength", wintypes.ULONG),
        ("TimeOutValue", wintypes.ULONG),
        ("DataBufferOffset", ctypes.c_size_t),
        ("SenseInfoOffset", wintypes.ULONG),
        ("Cdb", ctypes.c_ubyte * 16),
    ]


class SPTWB(ctypes.Structure):
    _fields_ = [
        ("spt", SCSI_PASS_THROUGH),
        ("Filler", wintypes.ULONG),
        ("Sense", ctypes.c_ubyte * 32),
    ]


# ---------------------------------------------------------------- ドライブ操作
def find_cdrom() -> str:
    """対象ドライブ文字 ('E:' 形式) を返す。DVD_DRIVE 環境変数があれば優先。"""
    env = os.environ.get("DVD_DRIVE")
    if env:
        return env.strip().rstrip(":").upper() + ":"
    for c in string.ascii_uppercase:
        if kernel32.GetDriveTypeW(f"{c}:\\") == DRIVE_CDROM:
            return f"{c}:"
    raise RuntimeError("No optical drive found")


def _decode_sense(sense: bytes) -> tuple[int, int, int]:
    code = sense[0] & 0x7F
    if code in (0x70, 0x71):      # fixed format
        return sense[2] & 0x0F, sense[12], sense[13]
    if code in (0x72, 0x73):      # descriptor format
        return sense[1] & 0x0F, sense[2], sense[3]
    return 0, 0, 0


def read_drive_state(drive: str) -> dict:
    """TEST UNIT READY を発行してトレイ状態を判定する。"""
    h = kernel32.CreateFileW(
        f"\\\\.\\{drive}", GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None,
    )
    if h is None or h == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())  # 5 = アクセス拒否
    try:
        pkt = SPTWB()
        pkt.spt.Length = ctypes.sizeof(SCSI_PASS_THROUGH)
        pkt.spt.CdbLength = 6                       # Cdb は全て0 = TEST UNIT READY
        pkt.spt.SenseInfoLength = len(pkt.Sense)
        pkt.spt.DataIn = SCSI_IOCTL_DATA_UNSPECIFIED
        pkt.spt.DataTransferLength = 0
        pkt.spt.TimeOutValue = 5
        pkt.spt.DataBufferOffset = 0
        pkt.spt.SenseInfoOffset = SPTWB.Sense.offset
        returned = wintypes.DWORD(0)
        ok = kernel32.DeviceIoControl(
            h, IOCTL_SCSI_PASS_THROUGH,
            ctypes.byref(pkt), ctypes.sizeof(pkt),
            ctypes.byref(pkt), ctypes.sizeof(pkt),
            ctypes.byref(returned), None,
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(h)

    key, asc, ascq = _decode_sense(bytes(pkt.Sense))
    status = pkt.spt.ScsiStatus
    if status == 0:
        state = "closed_disc"                       # 閉じていてディスクあり
    elif asc == 0x3A and ascq == 0x02:
        state = "open"
    elif asc == 0x3A and ascq == 0x01:
        state = "closed_empty"
    elif asc == 0x3A:
        state = "no_media_unspecified"              # ドライブによっては開閉の区別不可
    elif asc == 0x04:
        state = "becoming_ready"                    # 開閉・認識の途中
    else:
        state = "unknown"
    return {
        "drive": drive, "state": state, "scsi_status": status,
        "sense_key": key, "asc": f"{asc:02X}", "ascq": f"{ascq:02X}",
    }


def _mci(cmd: str) -> str:
    buf = ctypes.create_unicode_buffer(256)
    err = winmm.mciSendStringW(cmd, buf, 255, None)
    if err:
        msg = ctypes.create_unicode_buffer(256)
        winmm.mciGetErrorStringW(err, msg, 255)
        raise RuntimeError(f"MCI error {err}: {msg.value} ({cmd})")
    return buf.value


def _door(drive: str, action: str) -> None:
    alias = "deskpresence"
    _mci(f"open {drive} type cdaudio alias {alias}")
    try:
        _mci(f"set {alias} door {action}")
    finally:
        _mci(f"close {alias}")


def eject(drive: str) -> None:
    _door(drive, "open")


def close_tray(drive: str) -> None:
    _door(drive, "closed")


def poll_state(drive: str) -> str:
    """ポーリング用。一時的なエラーは 'error' として握りつぶす。"""
    try:
        return read_drive_state(drive)["state"]
    except OSError:
        return "error"


async def timed_poll(drive: str, soft_limit: float | None = None) -> tuple[str, float]:
    """poll_state を実行し (state, 所要秒) を返す。
    soft_limit 秒で返らなければ 'busy' とする（スレッドは裏で完了まで走り続ける）。"""
    t0 = time.monotonic()
    try:
        state = await asyncio.wait_for(asyncio.to_thread(poll_state, drive), soft_limit)
    except asyncio.TimeoutError:
        state = "busy"
    return state, time.monotonic() - t0


# 「トレイが閉じ方向に動いた/閉じた」とみなす状態
CLOSED_LIKE = {"closed_empty", "closed_disc", "becoming_ready", "no_media_unspecified"}

FAST_DETECT = os.environ.get("PRESENCE_FAST_DETECT") == "1"
BUSY_SOFT_LIMIT = 1.5  # 秒。open 確認後の TUR がこれを超えたら「ドライブ動作中」とみなす
OPEN_CONFIRM_SEC = 5.0  # eject 完了後、この秒数「開」を観測できなければ早閉じ等と判断して打ち切る

# ---------------------------------------------------------------- MCP
HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8765"))

# 2.x は host/port を run() に、1.x はコンストラクタに渡す
mcp = _Server("desk-presence") if MCP_V2 else _Server("desk-presence", host=HOST, port=PORT)
_lock = asyncio.Lock()  # ドライブは同時に1コマンドしか処理できないため直列化


@mcp.tool()
async def drive_status() -> dict:
    """Return the current tray state of the optical drive (for debugging).
    While presence_check is running, returns state="busy" immediately
    because the drive can only handle one command at a time."""
    if _lock.locked():
        return {"state": "busy", "note": "presence_check is running"}
    drive = find_cdrom()
    return await asyncio.to_thread(read_drive_state, drive)


@mcp.tool()
async def presence_check(
    ctx: Context,
    timeout_sec: Annotated[
        int, Field(ge=5, le=300, description="Seconds to wait for a human to close the tray")
    ] = 60,
    debug: Annotated[
        bool, Field(description="If true, include a per-poll trace (time, state, poll duration)")
    ] = False,
) -> dict:
    """Open the DVD tray and treat a human closing it as proof of presence.
    This tool does not return until the tray is closed (up to timeout_sec seconds).

    present: true = present / false = timed out (absent) / null = undetermined (see reason).
    reason: timeout | closed_before_open_confirmed (closed before it fully opened) |
            tray_open_not_detected | tray_already_open | already_running.
    response_sec is measured from the moment the tray was confirmed fully open;
    response_since_command_sec is measured from the eject command."""
    if _lock.locked():
        return {"present": None, "reason": "already_running"}
    async with _lock:
        return await _presence_check(ctx, timeout_sec, debug)


async def _presence_check(ctx: Context, timeout_sec: int, debug: bool) -> dict:
    drive = find_cdrom()
    trace: list[dict] = []

    def rec(t: float, state: str, dur: float) -> None:
        if debug and len(trace) < 300:
            trace.append({"t": round(t, 2), "state": state, "poll_sec": round(dur, 2)})

    def finish(result: dict) -> dict:
        if debug:
            result["trace"] = trace
        return result

    first = await asyncio.to_thread(read_drive_state, drive)  # 権限/ドライブ異常はここで例外化
    if first["state"] == "open":
        # すでに開いていると「閉じた＝今の応答」とは言えないので判定しない
        return finish({"present": None, "reason": "tray_already_open"})

    t_cmd = time.monotonic()
    await asyncio.to_thread(eject, drive)
    eject_sec = time.monotonic() - t_cmd

    # 1) 完全に開くまで待つ（開く途中を「閉じた」と誤判定しないため）
    #    eject(MCI)は開き切るまで戻らないので、通常は最初のポーリングで "open" になる。
    #    OPEN_CONFIRM_SEC 秒たっても "open" を観測できなければ打ち切る。
    last = first["state"]
    opened = False
    deadline = time.monotonic() + OPEN_CONFIRM_SEC
    while time.monotonic() < deadline:
        await asyncio.sleep(0.3)
        last, dur = await timed_poll(drive)
        rec(time.monotonic() - t_cmd, last, dur)
        if last == "open":
            opened = True
            break
    if not opened:
        if last in CLOSED_LIKE:
            # 開き切る前に人間が閉じた（早閉じ）可能性が高い。
            # ただしイジェクト失敗と観測上は区別できないため present は None のまま。
            return finish({
                "present": None,
                "reason": "closed_before_open_confirmed",
                "hint": (
                    f"For {OPEN_CONFIRM_SEC:g} seconds after the eject operation completed, the tray was not observed to be open; it remained closed. It is highly likely that a person closed it before it could fully open (premature closure). In typical scenarios, it is almost certain that a person closed it; the likelihood of an actual eject failure is extremely low."
                ),
                "last": {"state": last},
                "eject_sec": round(eject_sec, 1),
                "waited_sec": OPEN_CONFIRM_SEC,
            })
        return finish({
            "present": None, "reason": "tray_open_not_detected",
            "last": {"state": last}, "eject_sec": round(eject_sec, 1),
            "waited_sec": OPEN_CONFIRM_SEC,
        })
    open_confirmed = time.monotonic() - t_cmd

    def present(resp: float, evidence: str) -> dict:
        return {
            "present": True,
            "response_sec": round(resp, 1),
            "response_since_command_sec": round(open_confirmed + resp, 1),
            "eject_sec": round(eject_sec, 1),
            "evidence": evidence,
        }

    # 2) 人間が閉じるのを待つ（連続2回「閉じ系」で確定）
    soft = BUSY_SOFT_LIMIT if FAST_DETECT else None
    start = time.monotonic()
    streak = 0
    closed_at = 0.0
    while (elapsed := time.monotonic() - start) < timeout_sec:
        await asyncio.sleep(0.5)
        state, dur = await timed_poll(drive, soft)
        rec(time.monotonic() - t_cmd, state, dur)
        if state == "busy":
            # 開いているはずのトレイでTURが返らない＝ドライブが動作中（閉じ操作とみなす）
            return finish(present(elapsed, "drive_busy"))
        if state in CLOSED_LIKE:
            streak += 1
            if streak == 1:
                closed_at = elapsed
            if streak >= 2:
                return finish(present(closed_at, "closed_state"))
        elif state == "open":
            streak = 0
        await ctx.report_progress(
            elapsed, timeout_sec, "Waiting for the tray to be closed"
        )

    # 期限ちょうどに閉じられ、ポーリングが長引いて期限を超えた場合も在席として扱う
    if streak >= 1:
        return finish(present(closed_at, "closed_state"))

    # 3) タイムアウト：不在扱い。トレイは後始末として閉じる（ベストエフォート）
    try:
        await asyncio.to_thread(close_tray, drive)
    except Exception:
        pass
    return finish({"present": False, "reason": "timeout", "waited_sec": timeout_sec})


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")  # or "stdio"
    if MCP_V2 and transport != "stdio":
        mcp.run(transport, host=HOST, port=PORT)
    else:
        mcp.run(transport)


if __name__ == "__main__":
    main()
