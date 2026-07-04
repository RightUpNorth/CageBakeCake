"""PyInstaller entry point.

The real CLI lives in cagebakecake/__main__.py, but PyInstaller runs its entry
script as a top-level module, which breaks that file's relative imports. This
shim imports the package properly and delegates.
"""

from cagebakecake.__main__ import main

if __name__ == "__main__":
    main()
