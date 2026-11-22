import pytest

from load_rules import CycleError, RuleError, build_registry, load_rules, parse_range_c


@pytest.fixture(scope="module")
def reg():
    return load_rules()


def row(**kw):
    return {"PolMaster": kw.get("m", {}), "PolStakes": kw.get("s", {})}


def test_range_c_ast():
    ast = parse_range_c("PolMaster.SystemDate>:D:10", "PolMaster")
    assert (ast.ref, ast.op, ast.unit, ast.magnitude) == (("PolMaster", "SystemDate"), ">", "D", 10)


def test_index_and_policyfield_alias(reg):
    assert reg.rule("PolMaster", "PolicyType") is not None
    assert reg.rule("PolMaster", "Nope") is None


def test_list_str_single_object(reg):
    assert reg.validate_field("PolMaster", "PolicyType", row(m={"PolicyType": "DI"}))
    assert not reg.validate_field("PolMaster", "PolicyType", row(m={"PolicyType": "XX"}))


def test_or_of_and_branches(reg):
    ok = row(m={"JurisdictionState": "KA", "Language": "KANNADA"})
    bad_combo = row(m={"JurisdictionState": "KA", "Language": "TAMIL"})
    assert reg.validate_field("PolMaster", "Language", ok)
    assert not reg.validate_field("PolMaster", "Language", bad_combo)


def test_cross_table_guard(reg):
    ctx = row(m={"PolicyType": "AC"}, s={"StakerCodes.Unique": "INS"})
    assert reg.validate_field("PolStakes", "StakerCodes.Unique", ctx)
    ctx = row(m={"PolicyType": "AC"}, s={"StakerCodes.Unique": "SPS"})
    assert not reg.validate_field("PolStakes", "StakerCodes.Unique", ctx)


def test_range_int_with_guard(reg):
    ctx = row(s={"StakerCodes.Unique": "CH", "StakerAge": 10})
    assert reg.validate_field("PolStakes", "StakerAge", ctx)
    ctx = row(s={"StakerCodes.Unique": "CH", "StakerAge": 30})
    assert not reg.validate_field("PolStakes", "StakerAge", ctx)


def test_range_yyyymmdd(reg):
    assert reg.validate_field("PolMaster", "SystemDate", row(m={"SystemDate": 20200115}))
    assert not reg.validate_field("PolMaster", "SystemDate", row(m={"SystemDate": 20250502}))  # after range
    assert not reg.validate_field("PolMaster", "SystemDate", row(m={"SystemDate": 20230231}))  # not a real date
    assert not reg.validate_field("PolMaster", "SystemDate", row(m={"SystemDate": 202001}))    # month only


def test_range_c_days(reg):
    base = {"SystemDate": "2020-01-01"}
    assert reg.validate_field("PolMaster", "EffectiveDate", row(m={**base, "EffectiveDate": "2020-01-11"}))
    assert not reg.validate_field("PolMaster", "EffectiveDate", row(m={**base, "EffectiveDate": "2020-01-10"}))


def test_topo_order_respects_dependencies(reg):
    pos = {n: i for i, n in enumerate(reg.order)}
    for dep, dependents in reg.graph.items():
        for d in dependents:
            assert pos[dep] < pos[d]


def test_validate_row_reports(reg):
    v = reg.validate_row(row(m={"PolicyType": "XX", "JurisdictionState": "KA"}))
    assert [(x.field) for x in v] == ["PolicyType"]


def test_cycle_fails_at_load():
    raw = [
        {"Table": "T", "Field": "A", "AllowedValues": {"B": "x", "ListStr": ["1"]}},
        {"Table": "T", "Field": "B", "AllowedValues": {"A": "1", "ListStr": ["x"]}},
    ]
    with pytest.raises(CycleError):
        build_registry(raw)


def test_malformed_rule():
    with pytest.raises(RuleError):
        build_registry([{"Table": "T", "Field": "A", "AllowedValues": {"Foo": 1}}])


def test_registry_is_frozen(reg):
    with pytest.raises(TypeError):
        reg.rules[("x", "y")] = None
