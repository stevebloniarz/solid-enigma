from scrapers.zillow import ZillowScraper
from scrapers.redfin import RedfinScraper
from scrapers.realtor import RealtorScraper

SCRAPERS = {
    "zillow": ZillowScraper,
    "redfin": RedfinScraper,
    "realtor": RealtorScraper,
}
