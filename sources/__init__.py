from importlib import import_module


ALL_SOURCES = {
    "arxiv": ("sources.arxiv_source", "ArxivSource"),
    "biorxiv": ("sources.biorxiv_source", "BiorxivSource"),
    "nature": ("sources.nature_source", "NatureSource"),
    "science": ("sources.science_source", "ScienceSource"),
    "acs": ("sources.acs_source", "ACSSource"),
}


def get_source_class(name: str):
    """Resolve a configured source name to its implementation class."""
    module_name, class_name = ALL_SOURCES[name]
    module = import_module(module_name)
    return getattr(module, class_name)
