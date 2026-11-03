from invenio_assets.webpack import WebpackThemeBundle

theme = WebpackThemeBundle(
    __name__,
    "assets",
    default="semantic-ui",
    themes={
        "semantic-ui": dict(
            entry={
                "spectra-mzml-previewer": "./js/spectra/mzml-previewer.js",
            },
            dependencies={},
            devDependencies={},
            aliases={},
        )
    },
)
