"""Entry point for the todo CLI."""
import sys

import cli


def main():
    cli.main(sys.argv[1:])


if __name__ == "__main__":
    main()
