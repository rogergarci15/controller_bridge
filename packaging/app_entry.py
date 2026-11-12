"""Punto de entrada del ejecutable de PyInstaller."""
import sys

from zwiftplay.app import main

if __name__ == "__main__":
    sys.exit(main())
