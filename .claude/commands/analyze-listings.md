# analyze-listings

Analyze house listings produced by hhunter and write AI notes back to the JSON file.

## Steps

1. **Find the file**: Look for the most recently modified `hhunter_*.json` or `listings.json`
   in the current directory and in `hhunter/`. Use `ls -t hhunter_*.json listings.json 2>/dev/null | head -1`
   or the equivalent to locate it. If $ARGUMENTS is set, treat it as the file path directly.

2. **Read the file**: Load the full JSON array of listing objects.

3. **For each listing**, analyze the following fields together:
   - `address`, `city`, `state`, `zip_code`
   - `price`, `price_per_sqft`, `price_assessment`
   - `beds`, `baths`, `sqft`, `year_built`, `lot_size_sqft`
   - `heating`, `cooling`, `sewer`, `water`, `parking`, `basement`
   - `days_on_market`
   - `description` (read the full text if present)
   - `image_urls` (note them — you cannot fetch images but flag if they're present)
   - `commute_minutes_am`, `commute_minutes_pm`, `within_commute_limit`

   Write a **2–4 sentence** `notable_features` string that covers:
   - **Red flags**: "as-is", mention of foundation/roof/mold/flood/major repairs, very high DOM (>90 days), price marked "high"
   - **Standouts**: unusually large lot, new construction, recently renovated, price marked "low", short commute
   - **Systems notes**: if heating/cooling/sewer data is present, flag anything unusual (e.g., oil heat, septic, no HVAC listed)
   - **Commute**: if commute exceeds the limit or is not yet calculated, note it
   - If nothing stands out, write: "No notable concerns or highlights from available data."

4. **Write the results**: For each listing, set `notable_features` to your analysis.
   Overwrite any listing whose `notable_features` is `"pending — run /analyze-listings"`
   or is `null`/empty. Do not overwrite entries that already have real analysis.

5. **Save the file**: Write the updated JSON array back to the same file path (preserving
   all other fields exactly as they were — do not reformat or reorder unrelated fields).

6. **Report**: Print a summary table: listing address | price | price_assessment | one-line notable_features excerpt.

## Notes

- Process all listings in one pass — reading them together lets you do relative comparisons
  (e.g., "cheapest listing in the set", "highest $/sqft").
- Be concise. Buyers skim this column. Lead with the most important finding.
- If `description` is empty/null for most listings, note that in the summary.
- The JSON field name is `notable_features` (snake_case).
