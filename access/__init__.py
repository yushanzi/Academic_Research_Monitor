from .open_access import OpenAccessDocumentAccessProvider


def get_access_provider(mode: str, app_config=None):
    if mode == "open_access":
        if app_config is None:
            return OpenAccessDocumentAccessProvider()
        sources = app_config.sources if hasattr(app_config, "sources") else (app_config.get("sources", {}) or {})
        network = app_config.network if hasattr(app_config, "network") else (app_config.get("network", {}) or {})
        return OpenAccessDocumentAccessProvider(source_settings=sources, network=network)
    if mode == "authenticated":
        raise NotImplementedError("access.mode='authenticated' is not implemented yet")
    raise ValueError(f"Unknown access mode: {mode}")
