# Silu native toolchain

This archive contains the self-hosted `siluc` compiler driver and its
companion `siluc1`. Keep the two executables in the same directory.
No Python installation is needed to use them.

Requirements: macOS or Linux on the architecture named in the archive,
plus `clang` on PATH (Xcode Command Line Tools on macOS;
`sudo apt install clang` on Debian/Ubuntu).

```sh
tar -xzf siluc-<version>-<platform>.tar.gz
cd siluc-<version>-<platform>
chmod +x siluc siluc1
./siluc fib.si -o fib
./fib
./siluc your_program.si -o your_program
```

The compiler's runtime objects are cached in `$XDG_CACHE_HOME/silu-runtime`
or `~/.cache/silu-runtime`. This is an early-stage binary release of a
Python-syntax subset, not a drop-in replacement for CPython. See the
language and semantics documentation at https://silu.askender.xyz/.
