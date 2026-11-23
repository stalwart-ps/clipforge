import time
import httpx


def launch_desktop(url: str, title: str = "ClipForge Local", width: int = 1360, height: int = 880):
    """Launch native OS window using pywebview (WebView2 on Windows)."""
    import webview

    # Wait up to 5 seconds for backend to be ready
    for _ in range(25):
        try:
            r = httpx.get(url, timeout=0.5)
            if r.status_code in (200, 404):
                break
        except Exception:
            time.sleep(0.2)

    window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        min_size=(1024, 680),
        text_select=True,
    )
    webview.start()
