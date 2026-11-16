"""Chạy giao diện chat cục bộ với đúng một worker."""

import argparse

import uvicorn


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    print(f"Giao diện chat: http://{args.host}:{args.port}", flush=True)
    uvicorn.run("legal_rag.api.app:create_app", factory=True,
                host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
