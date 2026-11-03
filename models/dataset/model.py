"""
Dataset
"""
from __future__ import annotations

from invenio_i18n import lazy_gettext as _
from oarepo_model.api import model
from oarepo_model.customizations import AddMetadataExport, AddServiceComponent
from oarepo_model.datatypes.registry import from_yaml
from ccmm_invenio.models import ccmm_production_preset_1_1_0

from common.spectra.components import SpectraIndexComponent

from .serializers import DataCiteJSONSerializer

# TODO: Consider letting users add an image/icon for the model,
# so that the deposit model selection page is more visually appealing.
dataset_model = model(
    "dataset",
    version="1.0.0",
    description="Dataset",
    presets=[

        ccmm_production_preset_1_1_0

    ],
    types=[
        from_yaml("metadata.yaml", __file__)
    ],
    metadata_type="Metadata",
    customizations=[
        # Add your customizations here, such as custom exports and class mixins. 
        # The list of available extensions is at https://github.com/oarepo/oarepo-model.
        # If you do not find a customization that suits your needs or need a
        # help with using customizations, please contact us at support@cesnet.cz and
        # specify the keyword "Invenio repository development" inside the subject or
        # mail body of the request.

        # export for datacite
        AddMetadataExport(
            code="datacite",
            name=_("Datacite export"),
            mimetype="application/vnd.datacite.datacite+json",
            serializer=DataCiteJSONSerializer()
        ),

        # index spectra of mzML files on publish (common/spectra)
        AddServiceComponent(SpectraIndexComponent),
    ],
    configuration={
        "ui_blueprint_name": "dataset_ui"
    }
)
