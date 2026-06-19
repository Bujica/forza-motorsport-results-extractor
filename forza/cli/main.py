from __future__ import annotations

from .parser import build_parser


def main() -> None:
    import sys

    if len(sys.argv) == 2 and sys.argv[1] == "?":
        sys.argv[1] = "--help"
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
