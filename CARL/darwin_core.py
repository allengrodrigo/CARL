"""
darwin_core.py — Darwin Core field registry for TaxonGPT.

Provides:
  DCField          — named tuple describing one Darwin Core term
  SECTIONS         — ordered list of Darwin Core class/section names
  FIELDS           — complete ordered list of DCField instances
  RECOMMENDED      — set of terms pre-selected as recommended defaults
  BY_SECTION       — dict mapping section name → list of DCField
  BY_TERM          — dict mapping term name → DCField

This module has no dependencies on any other TaxonGPT module and
contains no I/O or side effects — it is safe to import anywhere.

Sources:
  https://dwc.tdwg.org/terms/  (Darwin Core standard, 2021 ratified)
"""

from typing import NamedTuple


class DCField(NamedTuple):
    term:        str   # Darwin Core term (camelCase, e.g. "scientificName")
    section:     str   # Darwin Core class/section name
    description: str   # Brief human-readable description (~10 words)
    recommended: bool  # True = pre-selected in "Reset to recommended fields"


# ============================================================
# SECTIONS — display order matches the Darwin Core standard
# ============================================================

SECTIONS = [
    "Record-level",
    "Occurrence",
    "Organism",
    "MaterialSample",
    "Event",
    "Location",
    "GeologicalContext",
    "Identification",
    "Taxon",
    "MeasurementOrFact",
    "ResourceRelationship",
]


# ============================================================
# FIELDS — complete Darwin Core term list
# ============================================================

FIELDS: list[DCField] = [

    # ----------------------------------------------------------
    # Record-level
    # ----------------------------------------------------------
    DCField("type",                   "Record-level", "Nature or genre of the resource", False),
    DCField("modified",               "Record-level", "Most recent date the record was changed", False),
    DCField("language",               "Record-level", "Language of the resource", False),
    DCField("license",                "Record-level", "Legal document allowing resource use", False),
    DCField("rightsHolder",           "Record-level", "Person or organisation owning the resource", False),
    DCField("accessRights",           "Record-level", "Access restrictions on the resource", False),
    DCField("bibliographicCitation",  "Record-level", "Bibliographic citation for the resource", True),
    DCField("references",             "Record-level", "Related resource that references this one", False),
    DCField("institutionID",          "Record-level", "Identifier for the holding institution", False),
    DCField("collectionID",           "Record-level", "Identifier for the collection", False),
    DCField("datasetID",              "Record-level", "Identifier for the dataset", False),
    DCField("institutionCode",        "Record-level", "Acronym or abbreviation of the institution", True),
    DCField("collectionCode",         "Record-level", "Code identifying the collection", False),
    DCField("datasetName",            "Record-level", "Name of the dataset", False),
    DCField("ownerInstitutionCode",   "Record-level", "Institution that owns the object", False),
    DCField("basisOfRecord",          "Record-level", "Specific nature of the data record", False),
    DCField("informationWithheld",    "Record-level", "Information not provided in the record", False),
    DCField("dataGeneralizations",    "Record-level", "Actions taken to make data less specific", False),
    DCField("dynamicProperties",      "Record-level", "List of additional measurements or characteristics", False),

    # ----------------------------------------------------------
    # Occurrence
    # ----------------------------------------------------------
    DCField("occurrenceID",                    "Occurrence", "Globally unique identifier for the occurrence", False),
    DCField("catalogNumber",                   "Occurrence", "Identifier for the record in the collection", True),
    DCField("recordNumber",                    "Occurrence", "Identifier given at time of recording", False),
    DCField("recordedBy",                      "Occurrence", "Person who made the observation or collected the specimen", False),
    DCField("recordedByID",                    "Occurrence", "Identifier for the person who recorded the occurrence", False),
    DCField("individualCount",                 "Occurrence", "Number of individuals in the occurrence", False),
    DCField("organismQuantity",                "Occurrence", "Number or measurement of organisms", False),
    DCField("organismQuantityType",            "Occurrence", "Type of quantification for organismQuantity", False),
    DCField("sex",                             "Occurrence", "Sex of the organism(s)", False),
    DCField("lifeStage",                       "Occurrence", "Life stage of the organism(s)", False),
    DCField("reproductiveCondition",           "Occurrence", "Reproductive condition of the organism(s)", False),
    DCField("caste",                           "Occurrence", "Caste of the organism in a social group", False),
    DCField("behavior",                        "Occurrence", "Behavior shown by the organism at time of occurrence", False),
    DCField("vitality",                        "Occurrence", "Indication of whether organism was alive at recording", False),
    DCField("establishmentMeans",              "Occurrence", "How the organism came to be at the location", False),
    DCField("degreeOfEstablishment",           "Occurrence", "Degree to which organism is established at location", False),
    DCField("pathway",                         "Occurrence", "Process by which organism arrived at location", False),
    DCField("georeferenceVerificationStatus",  "Occurrence", "Indicator of georeference quality", False),
    DCField("occurrenceStatus",                "Occurrence", "Statement about presence or absence", False),
    DCField("preparations",                    "Occurrence", "Preparation or preservation method of specimen", False),
    DCField("disposition",                     "Occurrence", "Current state of the specimen relative to collection", False),
    DCField("associatedMedia",                 "Occurrence", "Media associated with the occurrence", False),
    DCField("associatedOccurrences",           "Occurrence", "Other occurrences associated with this one", False),
    DCField("associatedReferences",            "Occurrence", "Publications related to the occurrence", False),
    DCField("associatedSequences",             "Occurrence", "Genetic sequence information associated", False),
    DCField("associatedTaxa",                  "Occurrence", "Other taxa associated with the occurrence", False),
    DCField("otherCatalogNumbers",             "Occurrence", "Other catalog numbers for the same object", False),
    DCField("occurrenceRemarks",               "Occurrence", "Comments or notes about the occurrence", False),

    # ----------------------------------------------------------
    # Organism
    # ----------------------------------------------------------
    DCField("organismID",              "Organism", "Identifier for the organism instance", False),
    DCField("organismName",            "Organism", "Textual name or label assigned to the organism", False),
    DCField("organismScope",           "Organism", "Description of the kind of organism instance", False),
    DCField("associatedOrganisms",     "Organism", "Other organisms associated with this one", False),
    DCField("previousIdentifications", "Organism", "Prior identifications of the organism", False),
    DCField("organismRemarks",         "Organism", "Comments or notes about the organism", False),

    # ----------------------------------------------------------
    # MaterialSample
    # ----------------------------------------------------------
    DCField("materialSampleID", "MaterialSample", "Identifier for the material sample", False),

    # ----------------------------------------------------------
    # Event
    # ----------------------------------------------------------
    DCField("eventID",            "Event", "Identifier for the sampling event", False),
    DCField("parentEventID",      "Event", "Identifier for the broader event", False),
    DCField("eventType",          "Event", "Nature of the event", False),
    DCField("fieldNumber",        "Event", "Identifier given in the field during the event", False),
    DCField("eventDate",          "Event", "Date or interval during which the event occurred", False),
    DCField("eventTime",          "Event", "Time or interval during which the event occurred", False),
    DCField("startDayOfYear",     "Event", "Earliest ordinal day of the event", False),
    DCField("endDayOfYear",       "Event", "Latest ordinal day of the event", False),
    DCField("year",               "Event", "Four-digit year of the event", False),
    DCField("month",              "Event", "Integer month of the event", False),
    DCField("day",                "Event", "Integer day of the event", False),
    DCField("verbatimEventDate",  "Event", "Original textual representation of the date", False),
    DCField("habitat",            "Event", "Habitat category of the event site", False),
    DCField("samplingProtocol",   "Event", "Method or protocol used during the event", False),
    DCField("sampleSizeValue",    "Event", "Numeric value for the size of the sample", False),
    DCField("sampleSizeUnit",     "Event", "Unit of measurement for sampleSizeValue", False),
    DCField("samplingEffort",     "Event", "Amount of effort expended during the event", False),
    DCField("fieldNotes",         "Event", "Notes taken in the field during the event", False),
    DCField("eventRemarks",       "Event", "Comments or notes about the event", False),

    # ----------------------------------------------------------
    # Location
    # ----------------------------------------------------------
    DCField("locationID",                             "Location", "Identifier for the spatial region", False),
    DCField("higherGeographyID",                      "Location", "Identifier for higher geographic region", False),
    DCField("higherGeography",                        "Location", "Geographic region containing the location", False),
    DCField("continent",                              "Location", "Continent of the location", False),
    DCField("waterBody",                              "Location", "Name of the water body", False),
    DCField("islandGroup",                            "Location", "Name of the island group", False),
    DCField("island",                                 "Location", "Name of the island", False),
    DCField("country",                                "Location", "Name of the country of the location", False),
    DCField("countryCode",                            "Location", "ISO 3166-1-alpha-2 country code", False),
    DCField("stateProvince",                          "Location", "Name of the state or province", False),
    DCField("county",                                 "Location", "Name of the county or shire", False),
    DCField("municipality",                           "Location", "Name of the city, town, or municipality", False),
    DCField("locality",                               "Location", "Specific description of the place", False),
    DCField("verbatimLocality",                       "Location", "Original textual description of the place", False),
    DCField("minimumElevationInMeters",               "Location", "Lower limit of elevation in metres", False),
    DCField("maximumElevationInMeters",               "Location", "Upper limit of elevation in metres", False),
    DCField("verbatimElevation",                      "Location", "Original description of elevation", False),
    DCField("verticalDatum",                          "Location", "Vertical datum for depth/elevation values", False),
    DCField("minimumDepthInMeters",                   "Location", "Minimum depth below surface in metres", False),
    DCField("maximumDepthInMeters",                   "Location", "Maximum depth below surface in metres", False),
    DCField("verbatimDepth",                          "Location", "Original description of depth", False),
    DCField("minimumDistanceAboveSurfaceInMeters",    "Location", "Minimum distance above surface in metres", False),
    DCField("maximumDistanceAboveSurfaceInMeters",    "Location", "Maximum distance above surface in metres", False),
    DCField("locationAccordingTo",                    "Location", "Information source for the location", False),
    DCField("locationRemarks",                        "Location", "Comments or notes about the location", False),
    DCField("decimalLatitude",                        "Location", "Geographic latitude in decimal degrees", False),
    DCField("decimalLongitude",                       "Location", "Geographic longitude in decimal degrees", False),
    DCField("geodeticDatum",                          "Location", "Geodetic datum for lat/lon coordinates", False),
    DCField("coordinateUncertaintyInMeters",          "Location", "Horizontal distance in metres from coordinates", False),
    DCField("coordinatePrecision",                    "Location", "Decimal representation of coordinate precision", False),
    DCField("pointRadiusSpatialFit",                  "Location", "Ratio of area of point-radius to true footprint", False),
    DCField("verbatimCoordinates",                    "Location", "Original spatial coordinates of the location", False),
    DCField("verbatimLatitude",                       "Location", "Original latitude of the location", False),
    DCField("verbatimLongitude",                      "Location", "Original longitude of the location", False),
    DCField("verbatimCoordinateSystem",               "Location", "Coordinate format for verbatim coordinates", False),
    DCField("verbatimSRS",                            "Location", "Spatial reference system for verbatim coordinates", False),
    DCField("footprintWKT",                           "Location", "WKT representation of the location shape", False),
    DCField("footprintSRS",                           "Location", "Spatial reference system for footprintWKT", False),
    DCField("footprintSpatialFit",                    "Location", "Ratio of footprint area to true footprint", False),
    DCField("georeferencedBy",                        "Location", "Person who georeferenced the occurrence", False),
    DCField("georeferencedDate",                      "Location", "Date the occurrence was georeferenced", False),
    DCField("georeferenceProtocol",                   "Location", "Method used to determine the georeference", False),
    DCField("georeferenceSources",                    "Location", "Maps or references used for georeferencing", False),
    DCField("georeferenceRemarks",                    "Location", "Notes on the spatial description", False),

    # ----------------------------------------------------------
    # GeologicalContext
    # ----------------------------------------------------------
    DCField("geologicalContextID",             "GeologicalContext", "Identifier for the geological context", False),
    DCField("earliestEonOrLowestEonothem",     "GeologicalContext", "Earliest possible geological eon", False),
    DCField("latestEonOrHighestEonothem",      "GeologicalContext", "Latest possible geological eon", False),
    DCField("earliestEraOrLowestErathem",      "GeologicalContext", "Earliest possible geological era", False),
    DCField("latestEraOrHighestErathem",       "GeologicalContext", "Latest possible geological era", False),
    DCField("earliestPeriodOrLowestSystem",    "GeologicalContext", "Earliest possible geological period", False),
    DCField("latestPeriodOrHighestSystem",     "GeologicalContext", "Latest possible geological period", False),
    DCField("earliestEpochOrLowestSeries",     "GeologicalContext", "Earliest possible geological epoch", False),
    DCField("latestEpochOrHighestSeries",      "GeologicalContext", "Latest possible geological epoch", False),
    DCField("earliestAgeOrLowestStage",        "GeologicalContext", "Earliest possible geological age", False),
    DCField("latestAgeOrHighestStage",         "GeologicalContext", "Latest possible geological age", False),
    DCField("lowestBiostratigraphicZone",      "GeologicalContext", "Lowest biostratigraphic zone of occurrence", False),
    DCField("highestBiostratigraphicZone",     "GeologicalContext", "Highest biostratigraphic zone of occurrence", False),
    DCField("lithostratigraphicTerms",         "GeologicalContext", "Lithostratigraphic terms for the occurrence", False),
    DCField("group",                           "GeologicalContext", "Full name of the lithostratigraphic group", False),
    DCField("formation",                       "GeologicalContext", "Full name of the lithostratigraphic formation", False),
    DCField("member",                          "GeologicalContext", "Full name of the lithostratigraphic member", False),
    DCField("bed",                             "GeologicalContext", "Full name of the lithostratigraphic bed", False),

    # ----------------------------------------------------------
    # Identification
    # ----------------------------------------------------------
    DCField("identificationID",                  "Identification", "Identifier for the identification", False),
    DCField("verbatimIdentification",            "Identification", "Taxonomic identification as it appeared in source", False),
    DCField("identificationQualifier",           "Identification", "Brief phrase qualifying the identification", False),
    DCField("typeStatus",                        "Identification", "Nomenclatural type status of the specimen", False),
    DCField("identifiedBy",                      "Identification", "Person who made the identification", False),
    DCField("identifiedByID",                    "Identification", "Identifier for the person who identified", False),
    DCField("dateIdentified",                    "Identification", "Date the identification was made", False),
    DCField("identificationReferences",          "Identification", "Publications used for the identification", False),
    DCField("identificationVerificationStatus",  "Identification", "Indicator of verification of the identification", False),
    DCField("identificationRemarks",             "Identification", "Comments or notes about the identification", False),

    # ----------------------------------------------------------
    # Taxon
    # ----------------------------------------------------------
    DCField("taxonID",                "Taxon", "Identifier for the taxon concept", False),
    DCField("scientificNameID",       "Taxon", "Identifier for the nomenclatural details of the name", True),
    DCField("acceptedNameUsageID",    "Taxon", "Identifier for the accepted name usage", False),
    DCField("parentNameUsageID",      "Taxon", "Identifier for the parent name usage", False),
    DCField("originalNameUsageID",    "Taxon", "Identifier for the original name usage", False),
    DCField("nameAccordingToID",      "Taxon", "Identifier for the taxon concept reference", False),
    DCField("namePublishedInID",      "Taxon", "Identifier for the publication of the name", False),
    DCField("taxonConceptID",         "Taxon", "Identifier for the taxon concept", False),
    DCField("scientificName",         "Taxon", "Full scientific name with authorship and date", True),
    DCField("acceptedNameUsage",      "Taxon", "Full name of the accepted taxon", True),
    DCField("parentNameUsage",        "Taxon", "Full name of the immediate parent taxon", True),
    DCField("originalNameUsage",      "Taxon", "Original name under which the taxon was described", True),
    DCField("nameAccordingTo",        "Taxon", "Reference for the taxon concept", False),
    DCField("namePublishedIn",        "Taxon", "Reference where the name was originally published", True),
    DCField("namePublishedInYear",    "Taxon", "Year the name was originally published", True),
    DCField("higherClassification",   "Taxon", "Taxon names at ranks above the identified taxon", False),
    DCField("kingdom",                "Taxon", "Kingdom in which the taxon is classified", True),
    DCField("phylum",                 "Taxon", "Phylum in which the taxon is classified", True),
    DCField("class",                  "Taxon", "Class in which the taxon is classified", True),
    DCField("order",                  "Taxon", "Order in which the taxon is classified", True),
    DCField("superfamily",            "Taxon", "Superfamily in which the taxon is classified", False),
    DCField("family",                 "Taxon", "Family in which the taxon is classified", True),
    DCField("subfamily",              "Taxon", "Subfamily in which the taxon is classified", False),
    DCField("tribe",                  "Taxon", "Tribe in which the taxon is classified", False),
    DCField("subtribe",               "Taxon", "Subtribe in which the taxon is classified", False),
    DCField("genus",                  "Taxon", "Genus in which the taxon is classified", True),
    DCField("genericName",            "Taxon", "Genus part of the scientificName", False),
    DCField("subgenus",               "Taxon", "Subgenus in which the taxon is classified", False),
    DCField("infragenericEpithet",    "Taxon", "Infrageneric part of a trinomial name", False),
    DCField("specificEpithet",        "Taxon", "Species epithet of the scientificName", False),
    DCField("infraspecificEpithet",   "Taxon", "Infraspecific epithet of the scientificName", False),
    DCField("cultivarEpithet",        "Taxon", "Cultivar epithet of the scientificName", False),
    DCField("taxonRank",              "Taxon", "Taxonomic rank of the most specific name", True),
    DCField("verbatimTaxonRank",      "Taxon", "Taxonomic rank as it appeared in the source", False),
    DCField("scientificNameAuthorship","Taxon","Authorship information for the scientificName", True),
    DCField("vernacularName",         "Taxon", "Common or vernacular name for the taxon", False),
    DCField("nomenclaturalCode",      "Taxon", "Nomenclatural code governing the name", True),
    DCField("taxonomicStatus",        "Taxon", "Status of the name usage according to the checklist", True),
    DCField("nomenclaturalStatus",    "Taxon", "Status related to the original publication of the name", True),
    DCField("taxonRemarks",           "Taxon", "Comments or notes about the taxon", False),

    # ----------------------------------------------------------
    # MeasurementOrFact
    # ----------------------------------------------------------
    DCField("measurementID",               "MeasurementOrFact", "Identifier for the measurement or fact", False),
    DCField("parentMeasurementID",         "MeasurementOrFact", "Identifier for a broader measurement", False),
    DCField("measurementType",             "MeasurementOrFact", "Nature of the measurement or fact", False),
    DCField("measurementValue",            "MeasurementOrFact", "Value of the measurement or fact", False),
    DCField("measurementAccuracy",         "MeasurementOrFact", "Accuracy of the measurement value", False),
    DCField("measurementUnit",             "MeasurementOrFact", "Units for the measurementValue", False),
    DCField("measurementDeterminedBy",     "MeasurementOrFact", "Person who determined the measurement", False),
    DCField("measurementDeterminedDate",   "MeasurementOrFact", "Date the measurement was determined", False),
    DCField("measurementMethod",           "MeasurementOrFact", "Method used to determine the measurement", False),
    DCField("measurementRemarks",          "MeasurementOrFact", "Comments or notes about the measurement", False),

    # ----------------------------------------------------------
    # ResourceRelationship
    # ----------------------------------------------------------
    DCField("resourceRelationshipID",      "ResourceRelationship", "Identifier for the relationship", False),
    DCField("resourceID",                  "ResourceRelationship", "Identifier for the subject resource", False),
    DCField("relationshipOfResourceID",    "ResourceRelationship", "Identifier for the relationship type", False),
    DCField("relatedResourceID",           "ResourceRelationship", "Identifier for the related resource", False),
    DCField("relationshipOfResource",      "ResourceRelationship", "Relationship of the resource to the related resource", False),
    DCField("relationshipAccordingTo",     "ResourceRelationship", "Source establishing the relationship", False),
    DCField("relationshipEstablishedDate", "ResourceRelationship", "Date the relationship was established", False),
    DCField("relationshipRemarks",         "ResourceRelationship", "Comments or notes about the relationship", False),
]


# ============================================================
# DERIVED LOOKUPS — built once at import time
# ============================================================

RECOMMENDED: set[str] = {f.term for f in FIELDS if f.recommended}

BY_SECTION: dict[str, list[DCField]] = {s: [] for s in SECTIONS}
for _f in FIELDS:
    BY_SECTION[_f.section].append(_f)

BY_TERM: dict[str, DCField] = {f.term: f for f in FIELDS}


# ============================================================
# TAXON CHECKLIST DISPLAY — sections, status tiers, vocab types
# Used by Settings > Databases 6-column field selector.
# Sections excluded: Identification, MeasurementOrFact, ResourceRelationship.
# Fields absent from TAXON_STATUS are hidden from the taxon-checklist display.
# ============================================================

TAXON_SECTIONS = [
    "Taxon", "Record-level", "Occurrence", "Organism", "Event",
    "Location", "GeologicalContext",
]

TAXON_STATUS: dict[str, str] = {
    # Record-level
    "bibliographicCitation":  "recommended",
    "institutionCode":        "recommended",
    "references":             "optional",
    "institutionID":          "optional",
    "collectionID":           "optional",
    "datasetID":              "optional",
    "datasetName":            "optional",
    "collectionCode":         "optional",
    "ownerInstitutionCode":   "optional",
    "informationWithheld":    "optional",
    "dataGeneralizations":    "optional",
    "dynamicProperties":      "optional",
    # Occurrence
    "occurrenceID":           "optional",
    "catalogNumber":          "optional",
    "recordNumber":           "optional",
    "recordedBy":             "optional",
    "recordedByID":           "optional",
    "sex":                    "optional",
    "lifeStage":              "optional",
    "reproductiveCondition":  "optional",
    "caste":                  "optional",
    "vitality":               "optional",
    "establishmentMeans":     "optional",
    "degreeOfEstablishment":  "optional",
    "occurrenceStatus":       "optional",
    "preparations":           "optional",
    "disposition":            "optional",
    "associatedMedia":        "optional",
    "associatedReferences":   "optional",
    "associatedSequences":    "optional",
    "associatedTaxa":         "optional",
    "otherCatalogNumbers":    "optional",
    "occurrenceRemarks":      "optional",
    # Organism
    "organismID":              "optional",
    "organismName":            "optional",
    "organismScope":           "optional",
    "associatedOrganisms":     "optional",
    "previousIdentifications": "optional",
    "organismRemarks":         "optional",
    # Event
    "eventDate":               "optional",
    "verbatimEventDate":       "optional",
    "year":                    "optional",
    "month":                   "optional",
    "day":                     "optional",
    "habitat":                 "optional",
    "samplingProtocol":        "optional",
    "fieldNotes":              "optional",
    "eventRemarks":            "optional",
    "eventID":                 "optional",
    "parentEventID":           "optional",
    "eventType":               "optional",
    "fieldNumber":             "optional",
    "startDayOfYear":          "optional",
    "endDayOfYear":            "optional",
    "sampleSizeValue":         "optional",
    "sampleSizeUnit":          "optional",
    "samplingEffort":          "optional",
    # Location
    "country":                 "optional",
    "countryCode":             "optional",
    "locality":                "optional",
    "verbatimLocality":        "optional",
    "stateProvince":           "optional",
    "county":                  "optional",
    "municipality":            "optional",
    "continent":               "optional",
    "waterBody":               "optional",
    "islandGroup":             "optional",
    "island":                  "optional",
    "higherGeographyID":       "optional",
    "higherGeography":         "optional",
    "decimalLatitude":         "optional",
    "decimalLongitude":        "optional",
    "geodeticDatum":           "optional",
    "coordinateUncertaintyInMeters":        "optional",
    "coordinatePrecision":     "optional",
    "verbatimCoordinates":     "optional",
    "verbatimLatitude":        "optional",
    "verbatimLongitude":       "optional",
    "verbatimCoordinateSystem":"optional",
    "verbatimSRS":             "optional",
    "verbatimElevation":       "optional",
    "minimumElevationInMeters":             "optional",
    "maximumElevationInMeters":             "optional",
    "minimumDepthInMeters":    "optional",
    "maximumDepthInMeters":    "optional",
    "verbatimDepth":           "optional",
    "minimumDistanceAboveSurfaceInMeters":  "optional",
    "maximumDistanceAboveSurfaceInMeters":  "optional",
    "locationID":              "optional",
    "locationAccordingTo":     "optional",
    "locationRemarks":         "optional",
    "footprintWKT":            "optional",
    "footprintSRS":            "optional",
    "georeferenceProtocol":    "optional",
    "georeferenceSources":     "optional",
    "georeferenceRemarks":     "optional",
    "georeferencedBy":         "optional",
    "georeferencedDate":       "optional",
    # GeologicalContext
    "geologicalContextID":              "optional",
    "earliestEonOrLowestEonothem":      "optional",
    "latestEonOrHighestEonothem":       "optional",
    "earliestEraOrLowestErathem":       "optional",
    "latestEraOrHighestErathem":        "optional",
    "earliestPeriodOrLowestSystem":     "optional",
    "latestPeriodOrHighestSystem":      "optional",
    "earliestEpochOrLowestSeries":      "optional",
    "latestEpochOrHighestSeries":       "optional",
    "earliestAgeOrLowestStage":         "optional",
    "latestAgeOrHighestStage":          "optional",
    "lowestBiostratigraphicZone":       "optional",
    "highestBiostratigraphicZone":      "optional",
    "lithostratigraphicTerms":          "optional",
    "group":                            "optional",
    "formation":                        "optional",
    "member":                           "optional",
    "bed":                              "optional",
    # Taxon
    "taxonID":                 "required",
    "scientificName":          "required",
    "taxonRank":               "required",
    "kingdom":                 "recommended",
    "phylum":                  "recommended",
    "class":                   "recommended",
    "order":                   "recommended",
    "family":                  "recommended",
    "genus":                   "recommended",
    "scientificNameAuthorship":"recommended",
    "namePublishedIn":         "recommended",
    "namePublishedInYear":     "recommended",
    "taxonomicStatus":         "recommended",
    "nomenclaturalStatus":     "recommended",
    "nomenclaturalCode":       "recommended",
    "scientificNameID":        "recommended",
    "parentNameUsage":         "recommended",
    "acceptedNameUsage":       "recommended",
    "originalNameUsage":       "recommended",
    "parentNameUsageID":       "recommended",
    "acceptedNameUsageID":     "recommended",
    "subfamily":               "optional",
    "superfamily":             "optional",
    "tribe":                   "optional",
    "subtribe":                "optional",
    "subgenus":                "optional",
    "specificEpithet":         "optional",
    "infraspecificEpithet":    "optional",
    "genericName":             "optional",
    "infragenericEpithet":     "optional",
    "cultivarEpithet":         "optional",
    "verbatimTaxonRank":       "optional",
    "higherClassification":    "optional",
    "vernacularName":           "optional",
    "nameAccordingTo":         "optional",
    "nameAccordingToID":       "optional",
    "namePublishedInID":       "optional",
    "originalNameUsageID":     "optional",
    "taxonConceptID":          "optional",
    "taxonRemarks":            "optional",
}

VOCAB_TYPE: dict[str, str] = {
    # Record-level
    "bibliographicCitation":  "Free text",
    "institutionCode":        "Free text",
    "references":             "URI",
    "institutionID":          "URI",
    "collectionID":           "URI",
    "datasetID":              "Free text",
    "datasetName":            "Free text",
    "collectionCode":         "Free text",
    "ownerInstitutionCode":   "Free text",
    "informationWithheld":    "Free text",
    "dataGeneralizations":    "Free text",
    "dynamicProperties":      "Free text",
    # Occurrence
    "occurrenceID":           "Free text",
    "catalogNumber":          "Free text",
    "recordNumber":           "Free text",
    "recordedBy":             "Free text",
    "recordedByID":           "URI",
    "sex":                    "Controlled",
    "lifeStage":              "Controlled",
    "reproductiveCondition":  "Free text",
    "caste":                  "Free text",
    "vitality":               "Controlled",
    "establishmentMeans":     "Controlled",
    "degreeOfEstablishment":  "Controlled",
    "occurrenceStatus":       "Controlled",
    "preparations":           "Pipe-sep",
    "disposition":            "Controlled",
    "associatedMedia":        "Pipe-sep",
    "associatedReferences":   "Pipe-sep",
    "associatedSequences":    "Pipe-sep",
    "associatedTaxa":         "Pipe-sep",
    "otherCatalogNumbers":    "Pipe-sep",
    "occurrenceRemarks":      "Free text",
    # Organism
    "organismID":              "Free text",
    "organismName":            "Free text",
    "organismScope":           "Free text",
    "associatedOrganisms":     "Pipe-sep",
    "previousIdentifications": "Pipe-sep",
    "organismRemarks":         "Free text",
    # Event
    "eventDate":               "ISO date",
    "verbatimEventDate":       "Free text",
    "year":                    "Integer",
    "month":                   "Integer",
    "day":                     "Integer",
    "habitat":                 "Free text",
    "samplingProtocol":        "Free text",
    "fieldNotes":              "Free text",
    "eventRemarks":            "Free text",
    "eventID":                 "Free text",
    "parentEventID":           "Free text",
    "eventType":               "Free text",
    "fieldNumber":             "Free text",
    "startDayOfYear":          "Integer",
    "endDayOfYear":            "Integer",
    "sampleSizeValue":         "Decimal",
    "sampleSizeUnit":          "Free text",
    "samplingEffort":          "Free text",
    # Location
    "country":                 "Free text",
    "countryCode":             "Controlled",
    "locality":                "Free text",
    "verbatimLocality":        "Free text",
    "stateProvince":           "Free text",
    "county":                  "Free text",
    "municipality":            "Free text",
    "continent":               "Controlled",
    "waterBody":               "Free text",
    "islandGroup":             "Free text",
    "island":                  "Free text",
    "higherGeographyID":       "URI",
    "higherGeography":         "Pipe-sep",
    "decimalLatitude":         "Decimal",
    "decimalLongitude":        "Decimal",
    "geodeticDatum":           "Free text",
    "coordinateUncertaintyInMeters":        "Integer",
    "coordinatePrecision":     "Decimal",
    "verbatimCoordinates":     "Free text",
    "verbatimLatitude":        "Free text",
    "verbatimLongitude":       "Free text",
    "verbatimCoordinateSystem":"Controlled",
    "verbatimSRS":             "Free text",
    "verbatimElevation":       "Free text",
    "minimumElevationInMeters":             "Decimal",
    "maximumElevationInMeters":             "Decimal",
    "minimumDepthInMeters":    "Decimal",
    "maximumDepthInMeters":    "Decimal",
    "verbatimDepth":           "Free text",
    "minimumDistanceAboveSurfaceInMeters":  "Decimal",
    "maximumDistanceAboveSurfaceInMeters":  "Decimal",
    "locationID":              "URI",
    "locationAccordingTo":     "Free text",
    "locationRemarks":         "Free text",
    "footprintWKT":            "Free text",
    "footprintSRS":            "Free text",
    "georeferenceProtocol":    "Free text",
    "georeferenceSources":     "Pipe-sep",
    "georeferenceRemarks":     "Free text",
    "georeferencedBy":         "Free text",
    "georeferencedDate":       "ISO date",
    # GeologicalContext
    "geologicalContextID":              "Free text",
    "earliestEonOrLowestEonothem":      "Free text",
    "latestEonOrHighestEonothem":       "Free text",
    "earliestEraOrLowestErathem":       "Free text",
    "latestEraOrHighestErathem":        "Free text",
    "earliestPeriodOrLowestSystem":     "Free text",
    "latestPeriodOrHighestSystem":      "Free text",
    "earliestEpochOrLowestSeries":      "Free text",
    "latestEpochOrHighestSeries":       "Free text",
    "earliestAgeOrLowestStage":         "Free text",
    "latestAgeOrHighestStage":          "Free text",
    "lowestBiostratigraphicZone":       "Free text",
    "highestBiostratigraphicZone":      "Free text",
    "lithostratigraphicTerms":          "Free text",
    "group":                            "Free text",
    "formation":                        "Free text",
    "member":                           "Free text",
    "bed":                              "Free text",
    # Taxon
    "taxonID":                 "Free text",
    "scientificName":          "Free text",
    "taxonRank":               "Controlled",
    "kingdom":                 "Controlled",
    "phylum":                  "Free text",
    "class":                   "Free text",
    "order":                   "Free text",
    "family":                  "Free text",
    "genus":                   "Free text",
    "scientificNameAuthorship":"Free text",
    "namePublishedIn":         "Free text",
    "namePublishedInYear":     "Integer",
    "taxonomicStatus":         "Controlled",
    "nomenclaturalStatus":     "Controlled",
    "nomenclaturalCode":       "Controlled",
    "scientificNameID":        "URI",
    "parentNameUsage":         "Free text",
    "acceptedNameUsage":       "Free text",
    "originalNameUsage":       "Free text",
    "parentNameUsageID":       "Free text",
    "acceptedNameUsageID":     "Free text",
    "subfamily":               "Free text",
    "superfamily":             "Free text",
    "tribe":                   "Free text",
    "subtribe":                "Free text",
    "subgenus":                "Free text",
    "specificEpithet":         "Free text",
    "infraspecificEpithet":    "Free text",
    "genericName":             "Free text",
    "infragenericEpithet":     "Free text",
    "cultivarEpithet":         "Free text",
    "verbatimTaxonRank":       "Free text",
    "higherClassification":    "Pipe-sep",
    "vernacularName":           "Pipe-sep",
    "nameAccordingTo":         "Free text",
    "nameAccordingToID":       "URI",
    "namePublishedInID":       "URI",
    "originalNameUsageID":     "Free text",
    "taxonConceptID":          "URI",
    "taxonRemarks":            "Free text",
}

# Fields pre-selected in the Include checkbox by default:
# all terms rated "required" or "recommended" in TAXON_STATUS.
DEFAULT_INCLUDE_FIELDS: set[str] = {
    term for term, status in TAXON_STATUS.items()
    if status in ("required", "recommended")
}


# Allowed values for VOCAB_TYPE == "Controlled" fields.
# Terms absent from this dict fall back to a plain Entry widget.
CONTROLLED_VOCAB: dict[str, list[str]] = {
    "taxonRank": [
        "kingdom", "subkingdom", "phylum", "subphylum", "class", "subclass",
        "order", "suborder", "superfamily", "family", "subfamily", "tribe",
        "subtribe", "genus", "subgenus", "species", "subspecies", "variety",
        "form", "infraspecificname",
    ],
    "nomenclaturalCode": ["ICZN", "ICN", "ICNP", "ICTV", "ICVCN"],
    "taxonomicStatus": [
        "accepted", "synonym", "ambiguous synonym", "misapplied",
        "provisionally accepted", "doubtful",
    ],
    "nomenclaturalStatus": [
        "available", "unavailable", "legitimate", "illegitimate",
        "valid", "invalid", "conserved", "rejected",
        "nom. nov.", "nom. dub.", "nom. nud.", "nom. illeg.",
        "nom. cons.", "nom. rej.", "nomen dubium",
    ],
    "kingdom": [
        "Animalia", "Plantae", "Fungi", "Bacteria", "Archaea",
        "Chromista", "Protozoa", "Viruses",
    ],
    "sex": ["male", "female", "hermaphrodite", "undetermined"],
    "lifeStage": [
        "egg", "larva", "juvenile", "adult", "pupa", "nymph",
        "seedling", "sprout",
    ],
    "vitality": ["alive", "dead", "mixedLot", "uncertain"],
    "establishmentMeans": [
        "native", "nativeReintroduced", "introduced",
        "introducedAssistedColonisation", "vagrant", "uncertain",
    ],
    "degreeOfEstablishment": [
        "managed", "captive", "cultivated", "released", "failing",
        "casual", "reproducing", "established", "colonising",
        "invasive", "widespreadInvasive",
    ],
    "occurrenceStatus": ["present", "absent"],
    "disposition": [
        "inCollection", "missing", "voucher elsewhere", "duplicatesElsewhere",
    ],
    "continent": [
        "Africa", "Antarctica", "Asia", "Europe",
        "NorthAmerica", "Oceania", "SouthAmerica",
    ],
    "verbatimCoordinateSystem": [
        "decimal degrees", "degrees decimal minutes",
        "degrees minutes seconds", "UTM", "MGRS",
    ],
}
