from app.main import app

__all__ = ["app"]


def main():
    import argparse

    parser = argparse.ArgumentParser(prog="image-editor")
    parser.add_argument("mode", nargs="?", default="server", choices=["server", "gui"])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.mode == "gui":
        try:
            from app.gui import run_gui
        except ImportError as exc:
            raise SystemExit(
                f"gui mode needs the 'gui' extra: uv sync --extra gui ({exc})"
            )

        run_gui()
    else:
        import uvicorn

        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
