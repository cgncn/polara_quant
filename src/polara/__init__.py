from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("polara-quant")
except PackageNotFoundError:
    __version__ = "0.1.0-dev"
