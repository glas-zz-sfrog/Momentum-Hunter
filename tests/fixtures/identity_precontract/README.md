# Pre-Contract Shadow Fixture

`state.json` is exact synthetic offline output from canonical
`2bceeeadd06f5ed85943942f1c0f81b7094620f7`, before the lifecycle-position
contract existed. `origin.json` records the hash and executable provenance.
It is not historical market evidence. It was created with that revision's
own test report, allocation helper, Shadow service and FakeBroker, not by
deleting provenance from a modern record. No serialized bytes were rewritten.
The temporary report path is documentary; tests use the frozen embedded source.

Reproduction source and its execution identity are preserved in the Repair-002
external evidence packet as `make_precontract_fixture.py`.
