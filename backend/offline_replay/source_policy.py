"""Fixed-source, stdlib-only projection of the Serper ingestion classification gate."""

import ast
import hashlib
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def constant(source: str, name: str, *, optional: bool = False) -> Any:
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if not isinstance(value, (dict, list, tuple, set)):
                raise ValueError("Invalid source policy constant container")
            entries = list(value.items()) if isinstance(value, dict) else list(value)
            if not all(
                isinstance(item, str)
                or isinstance(item, tuple)
                and all(isinstance(v, str) for v in item)
                for item in entries
            ):
                raise ValueError("Invalid source policy constant")
            return value
    if optional:
        return set()
    raise ValueError(f"Missing source policy constant: {name}")


def load_function(source: str, name: str, namespace: dict[str, Any]) -> Any:
    functions = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(functions) != 1:
        raise ValueError("Missing source policy function")
    function = functions[0]
    calls = {
        "urlsplit",
        "urlunsplit",
        "parse_qsl",
        "urlencode",
        "canonicalize_url",
        "classify",
        "is_aggregator_domain",
        "any",
        "next",
        "len",
        "set",
        "ValueError",
    }
    methods = {
        "strip",
        "lower",
        "rstrip",
        "encode",
        "decode",
        "startswith",
        "endswith",
        "removeprefix",
        "split",
        "get",
        "items",
    }
    if function.decorator_list or function.args.defaults or function.args.kw_defaults:
        raise ValueError("Unexpected source policy function defaults")
    for node in ast.walk(function):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef)):
            raise ValueError("Source policy is not pure")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("Private source policy attribute")
        if isinstance(node, ast.Call) and not (
            isinstance(node.func, ast.Name)
            and node.func.id in calls
            or isinstance(node.func, ast.Attribute)
            and node.func.attr in methods
        ):
            raise ValueError("Unreviewed source policy call")
    function.returns = None
    for arg in function.args.args:
        arg.annotation = None
    tree = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    environment = {
        "__builtins__": {
            "any": any,
            "next": next,
            "len": len,
            "set": set,
            "ValueError": ValueError,
            "UnicodeError": UnicodeError,
        },
        "urlsplit": urlsplit,
        "urlunsplit": urlunsplit,
        "parse_qsl": parse_qsl,
        "urlencode": urlencode,
        **namespace,
    }
    exec(compile(tree, "<reviewed-source-classification>", "exec"), environment)  # noqa: S102
    return environment[name]


class SourcePolicy:
    def __init__(self, collection: str, scraper: str, presence: str, discovery: str):
        canonical = load_function(collection, "canonicalize_url", {})
        aggregator = load_function(
            scraper,
            "is_aggregator_domain",
            {"AGGREGATOR_DOMAINS": constant(scraper, "AGGREGATOR_DOMAINS")},
        )
        domains = constant(presence, "DOMAINS")
        classify = load_function(presence, "classify", {"DOMAINS": domains})
        self.classify = load_function(
            discovery,
            "classify_hit",
            {
                "canonicalize_url": canonical,
                "is_aggregator_domain": aggregator,
                "classify": classify,
                "DOMAINS": domains,
                "SOCIAL": constant(discovery, "SOCIAL"),
                "JOBS": constant(discovery, "JOBS"),
                "THIRD_PARTY_DOMAINS": constant(discovery, "THIRD_PARTY_DOMAINS", optional=True),
            },
        )
        self.source_hashes = {
            name: hashlib.sha256(source.encode()).hexdigest()
            for name, source in {
                "collection": collection,
                "scraper": scraper,
                "presence_platforms": presence,
                "collection_discovery": discovery,
            }.items()
        }

    def eligible(self, hit: dict[str, Any]) -> tuple[bool, str, str]:
        kind, reason = self.classify(hit)
        return (
            kind not in {"SOCIAL", "JOB_PR", "PORTAL_DIRECTORY", "OTHER", "ARTICLE"},
            kind,
            reason,
        )
