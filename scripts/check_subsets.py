import sys
from dataclasses import dataclass

import fastobo
from fastobo.id import PrefixedIdent
from fastobo.term import SubsetClause


def find_clauses_of(term, clause_tp: type):
    for clause in term:
        if isinstance(clause, clause_tp):
            yield clause

@dataclass
class CheckState:
    clause_found: bool
    subset_correct: bool

    def valid(self):
        return self.clause_found and self.subset_correct

    def __bool__(self):
        return self.valid()


def check_term(term) -> CheckState:
    subset_for = get_subset_for_id(term.id)
    for clause in term:
        if isinstance(clause, SubsetClause):
            if clause.raw_value() == subset_for:
                return CheckState(True, True)
            return CheckState(True, False)
    return CheckState(False, False)


def get_subset_for_id(id: PrefixedIdent):
    if id.prefix == 'PEFF':
        return "PEFF"
    elif id.prefix == 'NCIT':
        return "NCIT"
    elif id.prefix == "UO":
        return "UO"
    elif id.prefix != 'MS':
        return None
    v = str(id.local)[0]
    if v == '4':
        return "mzQC"
    elif v == '5':
        return "columns"
    elif v == '1' or v == '0':
        return 'core'


def main():
    path = sys.argv[1]
    cv = fastobo.load(path)
    failed = 0
    for term in cv:
        if isinstance(term.id, PrefixedIdent):
            if valid := check_term(term):
                continue
            subset = get_subset_for_id(term.id)
            if valid.clause_found:
                for clause in find_clauses_of(term, SubsetClause):
                    print(f"{term.id}|{term[0].name} had subset {clause.raw_value()} but needed {subset}")
            else:
                print(f"{term.id}|{term[0].name} needs subset {subset}")
            failed += 1

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()