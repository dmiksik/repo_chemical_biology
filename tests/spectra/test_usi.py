import pytest

from common.spectra.usi import (
    USI,
    InvalidUSI,
    build_usi,
    is_accession,
    ms_run_name,
    native_id_value,
    normalize_ms_run,
    parse_usi,
    scan_number,
)


def test_parse_usi_with_interpretation():
    usi = parse_usi("mzspec:PXD000561:Adult_Frontalcortex_bRP_Elite_85_f09:scan:17555:VLHPLEGAVVIIFK/2")
    assert usi == USI("PXD000561", "Adult_Frontalcortex_bRP_Elite_85_f09", "scan", "17555", "VLHPLEGAVVIIFK/2")
    assert usi.is_accession


def test_parse_usi_record_id_collection():
    usi = parse_usi("mzspec:a1b2c-3d4e5:run01:index:12")
    assert usi.collection == "a1b2c-3d4e5"
    assert not usi.is_accession
    assert usi.interpretation is None


def test_parse_usi_ms_run_with_colons():
    usi = parse_usi("mzspec:MSV000079514:ccms_peak/file:with:colons:scan:3")
    assert usi.ms_run == "ccms_peak/file:with:colons"
    assert usi.index == "3"


def test_parse_usi_native_id():
    assert parse_usi("mzspec:PXD000001:run:nativeId:1,1,2,1").index == "1,1,2,1"


@pytest.mark.parametrize(
    "value",
    ["", "mzspec:PXD000561:run:scan", "mzspec:PXD000561:run:spectrum:1", "foo:PXD000561:run:scan:1"],
)
def test_parse_usi_invalid(value):
    with pytest.raises(InvalidUSI):
        parse_usi(value)


def test_build_usi_roundtrip():
    value = build_usi("MSV000079514", "run01", "scan", 5, "PEPTIDE/2")
    assert value == "mzspec:MSV000079514:run01:scan:5:PEPTIDE/2"
    assert str(parse_usi(value)) == value


def test_build_usi_invalid_index_type():
    with pytest.raises(InvalidUSI):
        build_usi("PXD000001", "run", "trace", 1)


@pytest.mark.parametrize(
    "collection, expected",
    [("PXD000561", True), ("RPXD000561", True), ("MSV000079514", True), ("MSV0000795", False), ("a1b2c-3d4e5", False)],
)
def test_is_accession(collection, expected):
    assert is_accession(collection) is expected


def test_ms_run_name():
    assert ms_run_name("run01.mzML") == "run01"
    assert ms_run_name("run01.MZML") == "run01"
    assert ms_run_name("run01.mzML.gz") == "run01.mzML.gz"
    assert ms_run_name("run01.raw") == "run01"
    assert ms_run_name("run01.RAW") == "run01"


@pytest.mark.parametrize(
    "native_id, expected",
    [
        ("scan=17", 17),
        ("controllerType=0 controllerNumber=1 scan=17555", 17555),
        ("controllerType=4 controllerNumber=1 scan=3", None),
        ("index=5", None),
        ("sample=1 period=1 cycle=2 experiment=1", None),
    ],
)
def test_scan_number(native_id, expected):
    assert scan_number(native_id) == expected


@pytest.mark.parametrize(
    "ms_run, expected",
    [
        ("run01", "run01"),
        ("run01.mzML", "run01"),
        ("run01.raw", "run01"),
        ("peak/mzml_20230620_rt_ms2_positive/run01.mzML", "run01"),
        ("run.01", "run.01"),
    ],
)
def test_normalize_ms_run(ms_run, expected):
    assert normalize_ms_run(ms_run) == expected


def test_native_id_value():
    assert native_id_value("sample=1 period=1 cycle=2 experiment=1") == "1,1,2,1"
