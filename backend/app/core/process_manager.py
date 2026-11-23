import asyncio
from typing import Dict
import psutil


class ProcessManager:
    """Tracks active subprocess PIDs per project and cleanly terminates entire process trees."""

    _active_pids: Dict[str, int] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def register_process(cls, project_id: str, pid: int) -> None:
        async with cls._lock:
            cls._active_pids[project_id] = pid

    @classmethod
    async def unregister_process(cls, project_id: str) -> None:
        async with cls._lock:
            cls._active_pids.pop(project_id, None)

    @classmethod
    async def cancel_project(cls, project_id: str) -> bool:
        async with cls._lock:
            pid = cls._active_pids.pop(project_id, None)

        if not pid:
            return False

        try:
            parent = psutil.Process(pid)
            # Find all child processes recursively (e.g. yt-dlp, ffmpeg)
            children = parent.children(recursive=True)

            # Send SIGTERM to children first
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Terminate parent
            try:
                parent.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # Wait briefly for graceful termination
            _, alive = psutil.wait_procs(children + [parent], timeout=2.0)

            # If any process is still alive, kill forcefully
            for p in alive:
                try:
                    p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return True
        except Exception:
            return False
