            "model_beats_snapshot_market": (
                abs(model_error) < abs(market_error)
                if model_error is not None and market_error is not None
                else None
            ),
            "result_settled": result is not None,
        })

    # Earliest prospective snapshot per provider game key is the clean reference.
    first_by_game = {}
    for row in sorted(
        rows,
        key=lambda r: (
            str(r.get("captured_at_utc") or ""),
            str(r.get("snapshot_id") or ""),
        ),
    ):
        first_by_game.setdefault(row["game_key"], row)

    initial_rows = list(first_by_game.values())

    by_signal_groups = defaultdict(list)
    for row in initial_rows:
        by_signal_groups[row.get("signal") or "UNKNOWN"].append(row)

    by_signal = {
        signal: summarize(group)
        for signal, group in sorted(by_signal_groups.items())
    }

    initial_match_counts = defaultdict(int)
    for row in initial_rows:
        initial_match_counts[row.get("result_match_method") or "unknown"] += 1

    report = {
        "report_version": "prospective-settlement-v2-provider-independent-matching",
        "methodology": {
            "primary_reference": "Earliest timestamped prospective snapshot for each game.",
            "result_match_hierarchy": [
                "exact game ID",
                "exact normalized home/away teams + week",
                "exact normalized home/away teams + kickoff date",
                "unique high-confidence fuzzy home/away team match within same week",
            ],
            "fuzzy_match_floor": 0.92,
            "model_error": "Actual home margin minus Model A projected home margin.",
            "market_error": "Actual home margin minus market-implied home margin at snapshot.",
            "ats_result": (
                "Result for the model-preferred side using the market spread "
                "captured in that prospective snapshot."
            ),
            "totals_result": (
                "Result for weather-adjusted projected-total direction when the "
                "prospective edge was at least four points. Total Watch begins at seven."
            ),
            "total_clv": (
                "For flagged totals only, positive value means the prospective "
                "total was better than the near-kickoff closing proxy for the "
                "stated Over/Under direction."
            ),
            "closing_line": "Near-kickoff closing proxy, not asserted to be the canonical close.",
            "no_retroactive_model_changes": True,
        },
        "results_source": str(results_source.relative_to(ROOT)) if results_source else None,
        "counts": {
            "total_snapshot_rows": len(rows),
            "unique_snapshot_games": len(first_by_game),
            "completed_games_found": len(results),
            "initial_snapshots_settled": sum(1 for r in initial_rows if r["result_settled"]),
            "initial_snapshots_unmatched": sum(1 for r in initial_rows if not r["result_settled"]),
        },
        "result_match_methods_initial": dict(sorted(initial_match_counts.items())),
        "result_match_methods_all_snapshots": dict(sorted(match_method_counts.items())),
        "initial_snapshot_summary": summarize(initial_rows),
        "initial_snapshot_by_signal": by_signal,
        "all_snapshot_summary": summarize(rows),
        "rows": rows,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    fields = [
        "snapshot_id", "game_key", "result_game_id", "result_match_method",
        "captured_at_utc", "model_version", "week", "start_date",
        "away_team", "home_team", "preferred_side", "signal",
        "model_home_spread", "model_total", "model_home_win_probability",
        "public_home_spread", "public_total", "weather_applied",
        "weather_conditions_line", "weather_impact", "weather_total_adjustment",
        "weather_spread_adjustment", "weather_spread_status",
        "public_margin_error", "public_abs_error",
        "snapshot_home_spread", "snapshot_total", "snapshot_bookmaker",
        "total_direction", "total_edge", "total_tier", "total_result",
        "total_clv_points", "total_beat_close",
        "actual_total", "total_projection_error",
        "closing_home_spread", "closing_total", "clv_points", "home_points", "away_points",
        "actual_home_margin", "ats_result", "model_margin_error",
        "model_abs_error", "market_margin_error", "market_abs_error",
        "closing_margin_error", "closing_abs_error",
        "model_beats_snapshot_market", "result_settled",
    ]

    with REPORT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print("=" * 72)
    print("PROSPECTIVE RESULT SETTLEMENT COMPLETE")
    print("=" * 72)
    print("Snapshots:", len(rows))
    print("Unique games:", len(first_by_game))
    print("Results source:", report["results_source"] or "NONE — waiting for completed-game data")
    print("Completed results found:", len(results))
    print("Initial snapshots settled:", report["counts"]["initial_snapshots_settled"])
    print("Initial snapshots unmatched:", report["counts"]["initial_snapshots_unmatched"])
    print("Initial match methods:", dict(sorted(initial_match_counts.items())))
    print("JSON:", REPORT_JSON.relative_to(ROOT))
    print("CSV:", REPORT_CSV.relative_to(ROOT))


if __name__ == "__main__":
    main()
