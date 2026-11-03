"""Builder of small synthetic indexed mzML files for tests."""

from __future__ import annotations

import base64
import zlib
from array import array
from dataclasses import dataclass, field

HEADER = """<?xml version="1.0" encoding="utf-8"?>
<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">
<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0">
{file_header}<run id="test_run" defaultInstrumentConfigurationRef="IC1" startTimeStamp="2017-07-31T16:10:13Z">
<spectrumList count="{count}">
"""

# File-level metadata as written by msconvert for a Thermo file
FILE_HEADER = """<cvList count="1"><cv id="MS" fullName="PSI-MS" URI="psi-ms.obo"/></cvList>
<fileDescription>
<fileContent><cvParam cvRef="MS" accession="MS:1000580" name="MSn spectrum" value=""/></fileContent>
<sourceFileList count="1">
<sourceFile id="RAW1" name="test_run.raw" location="file:///C:/data">
<cvParam cvRef="MS" accession="MS:1000768" name="Thermo nativeID format" value=""/>
<cvParam cvRef="MS" accession="MS:1000569" name="SHA-1" value="d0bfe48c1e71d17020a60bdff9c931658d2c9065"/>
</sourceFile>
</sourceFileList>
</fileDescription>
<referenceableParamGroupList count="1">
<referenceableParamGroup id="CommonInstrumentParams">
<cvParam cvRef="MS" accession="MS:1001911" name="Q Exactive" value=""/>
<cvParam cvRef="MS" accession="MS:1000529" name="instrument serial number" value="Exactive Series slot #1"/>
</referenceableParamGroup>
</referenceableParamGroupList>
<softwareList count="2">
<software id="Xcalibur" version="2.8"><cvParam cvRef="MS" accession="MS:1000532" name="Xcalibur" value=""/></software>
<software id="pwiz" version="3.0.18353"><cvParam cvRef="MS" accession="MS:1000615" name="ProteoWizard software" value=""/></software>
</softwareList>
<instrumentConfigurationList count="2">
<instrumentConfiguration id="IC0"><cvParam cvRef="MS" accession="MS:1000031" name="instrument model" value=""/></instrumentConfiguration>
<instrumentConfiguration id="IC1">
<referenceableParamGroupRef ref="CommonInstrumentParams"/>
<componentList count="2">
<source order="1"><cvParam cvRef="MS" accession="MS:1000073" name="electrospray ionization" value=""/></source>
<analyzer order="2"><cvParam cvRef="MS" accession="MS:1000484" name="orbitrap" value=""/></analyzer>
</componentList>
<softwareRef ref="Xcalibur"/>
</instrumentConfiguration>
</instrumentConfigurationList>
<dataProcessingList count="1">
<dataProcessing id="pwiz_conversion">
<processingMethod order="0" softwareRef="pwiz">
<cvParam cvRef="MS" accession="MS:1000544" name="Conversion to mzML" value=""/>
</processingMethod>
</dataProcessing>
</dataProcessingList>
"""

SPECTRUM = """<spectrum index="{index}" id="{native_id}" defaultArrayLength="{length}">
<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="{ms_level}"/>
<scanList count="1"><scan>
<cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="{rt}" unitAccession="UO:0000031" unitName="minute"/>
</scan></scanList>
{precursor}<binaryDataArrayList count="2">
{mz_array}
{intensity_array}
</binaryDataArrayList>
</spectrum>
"""

PRECURSOR = """<precursorList count="1"><precursor><selectedIonList count="1"><selectedIon>
<cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="{mz}"/>
<cvParam cvRef="MS" accession="MS:1000041" name="charge state" value="{charge}"/>
</selectedIon></selectedIonList></precursor></precursorList>
"""

ARRAY = """<binaryDataArray encodedLength="{encoded_length}">
<cvParam cvRef="MS" accession="{type_acc}" name="{type_name}"/>
<cvParam cvRef="MS" accession="{compression_acc}" name="{compression_name}"/>
<cvParam cvRef="MS" accession="{kind_acc}" name="{kind_name}"/>
<binary>{data}</binary>
</binaryDataArray>"""

MIDDLE = """</spectrumList>
<chromatogramList count="1">
"""

CHROMATOGRAM = """<chromatogram index="0" id="TIC" defaultArrayLength="0"/>
"""

FOOTER = """</chromatogramList>
</run>
</mzML>
"""


@dataclass
class Spectrum:
    native_id: str
    mzs: list[float]
    intensities: list[float]
    ms_level: int = 2
    rt: float = 1.5
    precursor_mz: float | None = 445.12
    charge: int | None = 2


@dataclass
class MzMLFile:
    content: bytes
    offsets: dict[str, int] = field(default_factory=dict)


def _array(values, kind_acc, kind_name, zlib_compressed, float64):
    raw = array("d" if float64 else "f", values).tobytes()
    if zlib_compressed:
        raw = zlib.compress(raw)
    data = base64.b64encode(raw).decode()
    return ARRAY.format(
        encoded_length=len(data),
        type_acc="MS:1000523" if float64 else "MS:1000521",
        type_name="64-bit float" if float64 else "32-bit float",
        compression_acc="MS:1000574" if zlib_compressed else "MS:1000576",
        compression_name="zlib compression" if zlib_compressed else "no compression",
        kind_acc=kind_acc,
        kind_name=kind_name,
        data=data,
    )


def build_mzml(
    spectra: list[Spectrum], zlib_compressed: bool = True, float64: bool = True, file_header: bool = False
) -> MzMLFile:
    """Return an indexed mzML with the given spectra and its spectrum offsets.

    ``file_header`` adds file-level metadata (instrument, software, source file).
    """
    out = bytearray(
        HEADER.format(count=len(spectra), file_header=FILE_HEADER if file_header else "").encode()
    )
    offsets = {}
    for index, spectrum in enumerate(spectra):
        offsets[spectrum.native_id] = len(out)
        precursor = (
            PRECURSOR.format(mz=spectrum.precursor_mz, charge=spectrum.charge)
            if spectrum.precursor_mz is not None
            else ""
        )
        out += SPECTRUM.format(
            index=index,
            native_id=spectrum.native_id,
            length=len(spectrum.mzs),
            ms_level=spectrum.ms_level,
            rt=spectrum.rt,
            precursor=precursor,
            mz_array=_array(spectrum.mzs, "MS:1000514", "m/z array", zlib_compressed, float64),
            intensity_array=_array(
                spectrum.intensities, "MS:1000515", "intensity array", zlib_compressed, float64
            ),
        ).encode()
    out += MIDDLE.encode()
    chromatogram_offset = len(out)
    out += CHROMATOGRAM.encode()
    out += FOOTER.encode()

    index_list_offset = len(out)
    out += f'<indexList count="2">\n<index name="spectrum">\n'.encode()
    for native_id, offset in offsets.items():
        out += f'<offset idRef="{native_id}">{offset}</offset>\n'.encode()
    out += b'</index>\n<index name="chromatogram">\n'
    out += f'<offset idRef="TIC">{chromatogram_offset}</offset>\n'.encode()
    out += b"</index>\n</indexList>\n"
    out += f"<indexListOffset>{index_list_offset}</indexListOffset>\n".encode()
    out += b"<fileChecksum>0000000000000000000000000000000000000000</fileChecksum>\n</indexedmzML>\n"
    return MzMLFile(bytes(out), offsets)


def thermo_id(scan: int) -> str:
    return f"controllerType=0 controllerNumber=1 scan={scan}"
