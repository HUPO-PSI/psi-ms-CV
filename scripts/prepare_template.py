import sys
import csv

import fastobo

LEVEL1_HEADERS = [
    "ID",
    "LABEL",
    "TYPE",
    "Is a",
    "Part of",
    "Value Type",
    "Value Concept",
    "Has Units",
    "Has Order",
    "Has reg ex",
    "Has Metric",
    "Has Column",
    "Has Optional Column",
    "X-REFS",
    "Exact synonyms",
    "Related synonyms",
    "Definition",
    "Definition Citation",
    "Comments",
    "Namespace",
    "Subset",
    "editor",
]

LEVEL2_HEADERS = [
    "ID",
    "LABEL",
    "TYPE",
    "SC %  SPLIT=||",
    "SC part_of some %  SPLIT=||",
    "SC has_value_type some %  SPLIT=||",
    "SC has_value_concept some %  SPLIT=||",
    "SC has_units some %  SPLIT=||",
    "SC has_order some %  SPLIT=||",
    "SC has_regexp some %  SPLIT=||",
    "SC has_metric_category some %  SPLIT=||",
    "SC has_column some %  SPLIT=||",
    "SC has_optional_column some %  SPLIT=||",
    "A oboInOwl:hasDbXref SPLIT=||",
    "A oboInOwl:hasExactSynonym SPLIT=||",
    "A oboInOwl:hasRelatedSynonym SPLIT=||",
    "A IAO:0000115",
    ">A IAO:0000119 SPLIT=||",
    "A rdfs:comment",
    "A has_obo_namespace",
    "A in_subset",
    "A created_by",
]

DTYPES = ["string", "float", "integer", "double", "dateTime", "positiveInteger"]


def build_record(term: fastobo.term.TermFrame | fastobo.typedef.TypedefFrame) -> dict:
    """Convert a term or typedef into a dictionary representing a row of the template TSV"""
    record = {
        "ID": str(term.id) if isinstance(term.id, fastobo.id.PrefixedIdent) else "",
        "Is a": [],
        "TYPE": "owl:Class",
        "Part of": [],
        "Value Type": [],
        "Value Concept": [],
        "Has Units": [],
        "Has Order": [],
        "Has reg ex": [],
        "Has Metric": [],
        "Has Column": [],
        "Has Optional Column": [],
        "Has Domain": [],
        "X-REFS": [],
        "Exact synonyms": [],
        "Related synonyms": [],
        "Definition Citation": [],
    }

    for tag in term:
        match tag.raw_tag():
            case "name":
                if record["ID"]:
                    record["LABEL"] = tag.name
                else:
                    # All of our property typedefs are unprefixed
                    record["LABEL"] = tag.name.replace(" ", "_")
                    record["TYPE"] = "object property"
            case "def":
                record["Definition"] = tag.definition
                record["Definition Citation"].extend(map(str, tag.xrefs))
            case "is_a":
                record["Is a"].append(str(tag.term))
            case "synonym":
                if tag.synonym.scope == "EXACT":
                    record["Exact synonyms"].append(tag.synonym.desc)
                else:
                    record["Related synonyms"].append(tag.synonym.desc)
            case "comment":
                record["Comments"] = tag.comment
            case "xref":
                record["X-REFS"].append(str(tag.xref.id))
            case "relationship":
                match str(tag.typedef):
                    case "part_of":
                        record["Part of"].append(str(tag.term))
                    case "has_metric_category":
                        record["Has Metric"].append(str(tag.term))
                    case "has_value_concept":
                        record["Value Concept"].append(str(tag.term))
                    case "has_value_type":
                        record["Value Type"].append(str(tag.term))
                    case "has_units":
                        record["Has Units"].append(str(tag.term))
                    case "has_regexp":
                        record["Has reg ex"].append(str(tag.term))
                    case "has_column":
                        record["Has Column"].append(str(tag.term))
                    case "has_optional_column":
                        record["Has Optional Column"].append(str(tag.term))
                    case "has_order":
                        record["Has Order"].append(str(tag.term))
                    case "has_domain":
                        record["Has Domain"].append(str(tag.term))
                    case _:
                        print(f"Relationship type not covered: {tag}")
            case "namespace":
                record["Namespace"] = str(tag.namespace)
            #             case "subset":
            #                 record['Subset'] = str(tag.subset)
            case "created_by":
                record["editor"] = str(tag.creator)
    return record


def format_record(record: dict) -> dict:
    return {
        k: "||".join(map(str, v)) if isinstance(v, list) else str(v)
        for k, v in record.items()
    }


def main():
    cv_path = sys.argv[1]
    try:
        template_path = sys.argv[2]
    except IndexError:
        template_path = "ms_robot_template.tsv"
    cv = fastobo.load(cv_path)

    records: list[dict] = []

    # First generate references to the XSD types so that they are defined. Probably not necessary
    for dt in DTYPES:
        records.append(
            {
                "ID": f"xsd:{dt}",
                "LABEL": dt,
                "TYPE": "owl:Class",
            }
        )

    allowed_namespaces = ("MS", "PEFF")
    for entry in cv:
        if (
            isinstance(entry.id, fastobo.id.PrefixedIdent)
            and entry.id.prefix not in allowed_namespaces
        ):
            continue
        records.append(build_record(entry))

    with open(template_path, "wt", newline="", encoding="utf8") as fh:
        writer = csv.writer(fh, delimiter='\t')
        writer.writerow(LEVEL1_HEADERS)
        writer.writerow(LEVEL2_HEADERS)

        for rec in map(format_record, records):
            writer.writerow([rec.get(f) for f in LEVEL1_HEADERS])

if __name__ == "__main__":
    main()