import unittest

from unittest.mock import patch

from enterprise_boards import _workday_jobs, parse_enterprise_ref, sap_jobs_from_xml, workday_brand, workday_india_filter


class EnterpriseBoardTests(unittest.TestCase):
    def test_parses_workday_oracle_smartrecruiters_sap_and_taleo(self):
        cases = {
            "https://qualys.wd5.myworkdayjobs.com/en-US/Careers/job/Pune/Software-Engineer_R0004966": (
                "workday", "qualys.wd5.myworkdayjobs.com/careers",
            ),
            "https://ncratleos.wd1.myworkdayjobs.com/ext_apacatleos/job/GURGAON-IND/Azure-AI-Engineer_R1": (
                "workday", "ncratleos.wd1.myworkdayjobs.com/ext_apacatleos",
            ),
            "https://wd1.myworkdaysite.com/recruiting/wf/WellsFargoJobs/job/Hyderabad-India/Engineer_R-1": (
                "workday", "wd1.myworkdaysite.com/wf/wellsfargojobs",
            ),
            "https://jobs.smartrecruiters.com/BoschGroup/744000144250118-node-js-backend-development": (
                "smartrecruiters", "boschgroup",
            ),
            "https://ebdt.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions/preview/1687": (
                "oracle", "ebdt.fa.us2.oraclecloud.com/cx_1",
            ),
            "https://career8.successfactors.com/career?company=MoodysProd&career_job_req_id=14582": (
                "sap", "career8.successfactors.com/moodysprod",
            ),
            "https://career55.sapsf.eu/career?company=bellmicros": (
                "sap", "career55.sapsf.eu/bellmicros",
            ),
            "https://uhg.taleo.net/careersection/10780/jobdetail.ftl?job=2378670&lang=en": (
                "taleo", "uhg.taleo.net/10780",
            ),
        }
        for url, expected in cases.items():
            self.assertEqual(parse_enterprise_ref(url), expected, url)
        self.assertIsNone(parse_enterprise_ref("https://jobs.ashbyhq.com/openai/123"))

    def test_sap_xml_keeps_india_roles_and_drops_global_boilerplate(self):
        xml_text = """
        <Job-Listing>
        <Job>
          <JobTitle><![CDATA[Software Engineer]]></JobTitle>
          <Job-Description><![CDATA[<p>Build services in Hyderabad, India.</p>]]></Job-Description>
          <ReqId>10</ReqId>
          <Posted-Date>10/01/2026</Posted-Date>
        </Job>
        <Job>
          <JobTitle><![CDATA[Administrative Assistant]]></JobTitle>
          <Job-Description><![CDATA[<p>We are a global leader in risk.</p>]]></Job-Description>
          <ReqId>11</ReqId>
        </Job>
        </Job-Listing>
        """
        jobs, saw_india = sap_jobs_from_xml(xml_text, "career8.successfactors.com", "moodysprod")
        self.assertTrue(saw_india)
        self.assertEqual([job["title"] for job in jobs], ["Software Engineer"])
        self.assertEqual(jobs[0]["location"], "India")
        self.assertIn("career_job_req_id=10", jobs[0]["job_url"])

    def test_workday_legal_entity_maps_to_brand(self):
        cases = [
            ("8147 ASOL - Hyderabad 5 SEZ Company", "accenture.wd103.myworkdayjobs.com/accenturecareers", "Accenture"),
            ("BR Financial Solutions India Pvt Ltd - hyd", "broadridge.wd5.myworkdayjobs.com/careers", "Broadridge"),
            ("IN1 Cigna Health Solutions India Private Limited", "cigna.wd5.myworkdayjobs.com/cignacareers", "Cigna"),
            ("Viavi Solutions India Pvt. Ltd.", "viavisolutions.wd1.myworkdayjobs.com/careers", "Viavi Solutions"),
            ("630 F5 Networks India Private Limited", "ffive.wd5.myworkdayjobs.com/f5jobs", "F5"),
            ("I00162 GE India Industrial Pvt Ltd", "geaerospace.wd5.myworkdayjobs.com/ge_externalsite", "GE"),
            ("8750 Rio Tinto India Private Limited", "wd3.myworkdaysite.com/riotinto/riotinto_careers", "Rio Tinto"),
            ("7152 Glencore Information Services Pvt Ltd", "glencorecorp.wd3.myworkdayjobs.com/external",
             "Glencore Information Services Pvt Ltd"),
            ("Cytiva India Pvt Ltd", "danaher.wd1.myworkdayjobs.com/danaherjobs", "Cytiva India Pvt Ltd"),
            ("131 Morgan Stanley Advantage Svcs", "ms.wd5.myworkdayjobs.com/external", "Morgan Stanley Advantage Svcs"),
            ("23andMe, Inc.", "23andme.wd5.myworkdayjobs.com/23", "23andMe"),
            ("", "maersk.wd3.myworkdayjobs.com/maersk_careers", ""),
        ]
        for legal_name, slug, brand in cases:
            self.assertEqual(workday_brand(legal_name, slug), brand, legal_name)

    def test_workday_india_filter_uses_one_location_facet(self):
        country = [
            {"facetParameter": "locationCountry", "values": [
                {"descriptor": "United States of America", "count": 900, "id": "us"},
                {"descriptor": "India", "count": 77, "id": "in"},
            ]},
            {"facetParameter": "locations", "values": [
                {"descriptor": "Bengaluru, India", "count": 55, "id": "blr"},
            ]},
        ]
        self.assertEqual(workday_india_filter(country), {"locationCountry": ["in"]})
        nested_cities = [{"facetParameter": "locationMainGroup", "values": [
            {"facetParameter": "locations", "values": [
                {"descriptor": "Arizona", "count": 4, "id": "az"},
                {"descriptor": "Pune", "count": 107, "id": "pune"},
            ]},
        ]}]
        self.assertEqual(workday_india_filter(nested_cities), {"locations": ["pune"]})
        us_only = [{"facetParameter": "locations", "values": [
            {"descriptor": "Indianapolis, IN", "count": 3, "id": "indy"},
            {"descriptor": "Austin, TX", "count": 9, "id": "aus"},
        ]}]
        self.assertEqual(workday_india_filter(us_only), {})
        self.assertIsNone(workday_india_filter([{"facetParameter": "jobFamilyGroup", "values": []}]))

    def test_workday_board_without_india_costs_one_request(self):
        probe = {"total": 12, "facets": [{"facetParameter": "locations", "values": [
            {"descriptor": "Austin, TX", "count": 12, "id": "aus"},
        ]}]}
        with patch("enterprise_boards._request_json", return_value=probe) as request:
            jobs, saw_india = _workday_jobs("acme.wd5.myworkdayjobs.com/careers")
        self.assertEqual((jobs, saw_india), ([], False))
        self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
