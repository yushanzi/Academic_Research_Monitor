from .open_access import OpenAccessDocumentAccessProvider


def get_access_provider(mode: str):
    if mode == "open_access":
        return OpenAccessDocumentAccessProvider()
    if mode == "authenticated":
        raise NotImplementedError("access.mode='authenticated' is not implemented yet")
    raise ValueError(f"Unknown access mode: {mode}")
