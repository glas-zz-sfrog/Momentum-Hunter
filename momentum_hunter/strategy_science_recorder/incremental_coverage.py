"""Rebuildable V2 custody counters; never discovery or strategy authority.

Only receipt-verified normalized records enter. Canonical parent/eligibility/
outcome reconciliation is reused on each actual bounded dependency slice.
Historical full derive_coverage remains the independent explicit audit oracle.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from .canonical import canonical_json_bytes, sha256_hex
from .contract import HORIZONS
from .coverage import CoverageReconciliationError, derive_coverage, _ratio


def _id(value):
    return value.get('recorder_id', '') if isinstance(value, dict) else ''


class IncrementalCoverage:
    def __init__(self):
        self.hashes = {}
        self.families = Counter()
        self.cycles = {}
        self.observations = {}
        self.decisions = {}
        self.eligibilities = {}
        self.instruments = set()
        self.eligible_instruments = set()
        self.waiting_observations = {}
        self.rows_declared = 0
        self.slots = {}
        self.horizons = {h: {'received': 0, 'accounted': 0, 'usable': 0, 'present': 0, 'terminal': 0} for h in HORIZONS}
        self.record_visits = 0
        self.dependency_visits = 0
        self._template = derive_coverage(()).to_mapping()

    @staticmethod
    def _fingerprint(observation):
        return str(observation['instrument_identity']['instrument_identity_fingerprint_sha256'])

    def _slice(self, observation, decision=None, outcome=None):
        cycle_id = _id(observation.get('discovery_cycle_id'))
        cycle = self.cycles.get(cycle_id)
        if cycle is None:
            raise CoverageReconciliationError('Observation lacks its exact discovery denominator.')
        records = [cycle, observation]
        eligibility = self.eligibilities.get(self._fingerprint(observation))
        if eligibility is not None:
            records.append(eligibility)
        if decision is not None:
            records.append(decision)
        if outcome is not None:
            records.append(outcome)
        self.dependency_visits += len(records)
        return derive_coverage(records)

    def add(self, record, raw=None):
        raw = canonical_json_bytes(record) if raw is None else raw
        if canonical_json_bytes(record) != raw:
            raise CoverageReconciliationError('Derived record no longer matches its raw bytes.')
        identity = _id(record.get('record_id'))
        digest = sha256_hex(raw)
        if not identity:
            raise CoverageReconciliationError('Normalized record has no immutable identity.')
        previous = self.hashes.get(identity)
        if previous is not None:
            if previous != digest:
                raise CoverageReconciliationError('Immutable coverage identity conflicts.')
            return
        kind = str(record.get('record_type'))
        if kind == 'discovery-cycle':
            cycle_id = _id(record.get('record_id'))
            if cycle_id in self.cycles:
                raise CoverageReconciliationError('Discovery identity repeated.')
            self.cycles[cycle_id] = record
            count = record.get('returned_row_count')
            if isinstance(count, int) and not isinstance(count, bool):
                self.rows_declared += count
        elif kind == 'candidate-observation':
            observation_id = _id(record.get('observation_id'))
            if not observation_id or observation_id in self.observations:
                raise CoverageReconciliationError('Duplicate immutable observation identity detected.')
            result = self._slice(record)
            fingerprint = self._fingerprint(record)
            self.observations[observation_id] = record
            self.instruments.add(fingerprint)
            if result.eligible_instruments:
                self.eligible_instruments.add(fingerprint)
            else:
                self.waiting_observations.setdefault(fingerprint, []).append(record)
        elif kind == 'science-eligibility':
            fingerprint = str(record.get('instrument_identity_fingerprint_sha256'))
            previous = self.eligibilities.get(fingerprint)
            if previous is not None and previous.get('science_eligibility') != record.get('science_eligibility'):
                raise CoverageReconciliationError('One instrument has conflicting Science eligibility records.')
            self.eligibilities[fingerprint] = record
            # Every waiting observation is processed only once, on first actual
            # custody eligibility. No discovery record or clock is rewritten.
            waiting = self.waiting_observations.pop(fingerprint, ())
            for observation in waiting:
                if self._slice(observation).eligible_instruments:
                    self.eligible_instruments.add(fingerprint)
        elif kind == 'decision-event':
            decision_id = _id(record.get('decision_id'))
            if not decision_id or decision_id in self.decisions:
                raise CoverageReconciliationError('Duplicate immutable decision identity detected.')
            observation = self.observations.get(_id(record.get('observation_id')))
            if observation is None:
                raise CoverageReconciliationError('Decision lacks one exact observation parent.')
            self._slice(observation, record)
            self.decisions[decision_id] = record
        elif kind == 'outcome-observation':
            decision_id = _id(record.get('decision_id'))
            horizon = str(record.get('outcome_semantic', ''))
            if decision_id and horizon in HORIZONS:
                slot = (decision_id, horizon)
                if slot in self.slots:
                    raise CoverageReconciliationError('More than one outcome occupies a decision/horizon slot.')
                decision = self.decisions.get(decision_id)
                if decision is None:
                    raise CoverageReconciliationError('Outcome lacks an exact eligible decision parent.')
                observation = self.observations[_id(decision.get('observation_id'))]
                result = self._slice(observation, decision, record)
                self.slots[slot] = identity
                state = self.horizons[horizon]
                state['received'] += result.received_outcome_slots
                state['accounted'] += result.accounted_outcome_slots
                state['usable'] += result.usable_outcome_slots
                state['present'] += int(result.by_horizon[horizon]['numerator'])
                state['terminal'] += result.terminal_gap_slots
        self.hashes[identity] = digest
        self.families[kind] += 1
        self.record_visits += 1

    def snapshot(self, *, conflicts=0):
        # All loops here are bounded by the fixed schema/horizon count.
        if sum(self.families.values()) != len(self.hashes) or self.record_visits != len(self.hashes):
            raise CoverageReconciliationError('Derived coverage count/index contradiction.')
        result = deepcopy(self._template)
        decisions = len(self.decisions)
        expected = decisions * len(HORIZONS)
        received = sum(s['received'] for s in self.horizons.values())
        accounted = sum(s['accounted'] for s in self.horizons.values())
        usable = sum(s['usable'] for s in self.horizons.values())
        terminal = sum(s['terminal'] for s in self.horizons.values())
        accounting = _ratio(accounted, expected)
        usable_rate = _ratio(usable, expected)
        by_horizon = {}
        for horizon, state in self.horizons.items():
            metric = _ratio(state['present'], decisions)
            metric.update(received_slots=state['received'], accounted_slots=state['accounted'], nonterminal_slots=state['received'] - state['accounted'], terminal_gap_slots=state['terminal'], unaccounted_slots=decisions - state['accounted'])
            by_horizon[horizon] = metric
        metrics = result['metrics']
        metrics['DENOMINATOR_ROW_COVERAGE'] = _ratio(len(self.observations), self.rows_declared)
        metrics['OUTCOME_ELIGIBILITY_ACCOUNTING_COVERAGE'] = _ratio(len(self.eligible_instruments), len(self.instruments))
        metrics['OUTCOME_ATTEMPT_OR_GAP_RECEIPT_COVERAGE'] = accounting
        metrics['OUTCOME_ELIGIBLE_DECISION_COVERAGE'] = usable_rate
        metrics['OUTCOME_HORIZON_COVERAGE'] = {'by_horizon': by_horizon, 'denominator': expected, 'numerator': usable, 'state': 'AVAILABLE' if expected else 'NOT_APPLICABLE'}
        result.update(discovery_cycles=len(self.cycles), returned_rows_declared=self.rows_declared, candidate_observations=len(self.observations), unique_instruments=len(self.instruments), eligible_instruments=len(self.eligible_instruments), material_decisions=decisions, expected_outcome_slots=expected, received_outcome_slots=received, accounted_outcome_slots=accounted, nonterminal_outcome_slots=received - accounted, unaccounted_outcome_slots=expected - accounted, usable_outcome_slots=usable, terminal_gap_slots=terminal, outcome_accounting_rate_ppm=accounting['rate_ppm'], outcome_accounting_rate_state=accounting['state'], usable_outcome_rate_ppm=usable_rate['rate_ppm'], usable_outcome_rate_state=usable_rate['state'], by_horizon=by_horizon, conflicts=int(conflicts))
        return result
