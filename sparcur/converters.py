import rdflib
from sparcur.core import log, sparc
from pyontutils.core import OntId
from pyontutils.namespaces import TEMP, isAbout


class TripleConverter:
    # TODO consider putting mappings in a dict hierarchy
    # that reflects where they are in the schema??
    known_skipped = tuple()
    mapping = tuple()

    @classmethod
    def setup(cls):
        for attr, predicate in cls.mapping:
            def _func(self, value, p=predicate): return p, self.l(value)
            setattr(cls, attr, _func)

    def __init__(self, json_source):
        """ in case we want to do contextual things here """
        self._source = json_source

    def l(self, value):
        if isinstance(value, OntId):
            return value.u
        elif isinstance(value, str) and value.startswith('http'):
            return OntId(value).u
        else:
            return rdflib.Literal(value)

    def triples_gen(self, subject):
        if not isinstance(subject, rdflib.URIRef):
            subject = rdflib.URIRef(subject)

        for field, value in self._source.items():
            log.debug(f'{field} {value}')
            convert = getattr(self, field, None)
            if convert is not None:
                if isinstance(value, tuple) or isinstance(value, list):
                    values = value
                else:
                    values = value,
                
                for v in values:
                    yield (subject, *convert(v))

            elif field in self.known_skipped:
                pass

            else:
                log.warning(f'Unhandled {self.__class__.__name__} field: {field}')


class ContributorConverter(TripleConverter):
    known_skipped = 'contributor_orcid_id', 'name'
    mapping = (
        ('first_name', sparc.firstName),
        ('last_name', sparc.lastName),
        ('contributor_affiliation', TEMP.hasAffiliation),
        ('is_contact_person', sparc.isContactPerson),
        ('is_responsible_pi', sparc.isContactPerson),
        )
 
    def contributor_role(self, value):
        return TEMP.hasRole, TEMP[value]

ContributorConverter.setup()


class MetaConverter(TripleConverter):
    mapping = [
        ['principal_investigator', TEMP.hasResponsiblePrincialInvestigator],
        ['protocol_url_or_doi', TEMP.hasProtocol],
        ['award_number', TEMP.hasAwardNumber],
        ['species', isAbout],
        ['organ', isAbout],
        ['subject_count', TEMP.hasNumberOfSubjects],
        ['keywords', isAbout],
    ]
MetaConverter.setup()  # box in so we don't forget


class DatasetConverter(TripleConverter):
    mapping = [
        ['error_index', TEMP.errorIndex],
        ['submission_completeness_index', TEMP.submissionCompletenessIndex],
        ]
DatasetConverter.setup()


class SubjectConverter(TripleConverter):
    mapping = [
        ['age_cateogry', TEMP.hasAgeCategory],
        ['species', sparc.animalSubjectIsOfSpecies],
        ['group', TEMP.hasAssignedGroup],
    ]

    def genus(self, value): return sparc.animalSubjectIsOfGenus, self.l(value)
    def species(self, value): return sparc.animalSubjectIsOfSpecies, self.l(value)
    def strain(self, value): return sparc.animalSubjectIsOfStrain, self.l(value)
    def weight(self, value): return sparc.animalSubjectHasWeight, self.l(value)
    def mass(self, value): return self.weight(value)
    def sex(self, value): return TEMP.hasBiologicalSex, self.l(value)
    def gender(self, value): return sparc.hasGender, self.l(value)
    def age(self, value): return TEMP.hasAge, self.l(value)
SubjectConverter.setup()

