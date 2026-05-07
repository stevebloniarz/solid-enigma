import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, jsonify, render_template, request, send_file

from dotenv import load_dotenv

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/search", methods=["POST"])
    def api_search():
        data = request.json or {}
        try:
            from models import SearchParams
            from scrapers import SCRAPERS
            from analysis.price import assess_prices
            from analysis.ai_analysis import analyze_listings
            from commute.calculator import calculate_commutes

            params = SearchParams(
                location=data.get("location", ""),
                employer_address=data.get("employer_address", ""),
                max_commute_minutes=int(data.get("max_commute_minutes", 45)),
                min_beds=int(data.get("min_beds", 1)),
                max_beds=int(data["max_beds"]) if data.get("max_beds") else None,
                min_baths=float(data.get("min_baths", 1)),
                min_sqft=int(data["min_sqft"]) if data.get("min_sqft") else None,
                max_sqft=int(data["max_sqft"]) if data.get("max_sqft") else None,
                min_price=int(data["min_price"]) if data.get("min_price") else None,
                max_price=int(data["max_price"]) if data.get("max_price") else None,
                property_types=data.get("property_types", ["Houses"]),
                sources=data.get("sources", ["zillow", "redfin", "realtor"]),
            )

            all_listings = []
            errors = {}
            for source in params.sources:
                try:
                    scraper = SCRAPERS[source]()
                    results = scraper.search(params)
                    all_listings.extend(results)
                except Exception as e:
                    errors[source] = str(e)

            all_listings = assess_prices(all_listings)
            calculate_commutes(all_listings, params)

            if data.get("ai_analysis"):
                analyze_listings(all_listings, max_analyze=10)

            return jsonify({
                "count": len(all_listings),
                "errors": errors,
                "listings": [l.to_json_dict() for l in all_listings],
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/export/<fmt>", methods=["POST"])
    def api_export(fmt):
        data = request.json or {}
        from models import Listing
        from output.exporter import export_csv, export_json
        import tempfile, json

        listings_data = data.get("listings", [])
        listings = []
        for d in listings_data:
            d.pop("image_urls", None)
            try:
                listings.append(Listing(**{k: v for k, v in d.items() if k in Listing.__dataclass_fields__}))
            except Exception:
                continue

        with tempfile.NamedTemporaryFile(
            suffix=f".{fmt}", delete=False, mode="w"
        ) as f:
            tmp_path = f.name

        if fmt == "csv":
            export_csv(listings, tmp_path)
            mimetype = "text/csv"
            download_name = "listings.csv"
        else:
            export_json(listings, tmp_path)
            mimetype = "application/json"
            download_name = "listings.json"

        return send_file(tmp_path, mimetype=mimetype, as_attachment=True, download_name=download_name)

    return app
