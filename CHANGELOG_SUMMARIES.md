# Comparative Summaries Feature - Implementation Summary

## Overview
Added two new comparative summary endpoints to the coach stats dashboard:
- 14-day summary (current week vs 2 weeks ago)
- 28-day summary (current week vs 4 weeks ago)

These complement the existing 7-day summary (current week vs previous week).

## Backend Changes (app/routes.py)

### New Endpoints

#### 1. `/coach/stats/athlete/<athlete_id>/summary-14days.json`
- **Location**: Lines 1478-1596
- **Purpose**: Compare current week to week from 2 weeks ago
- **Comparison Date**: `current_week_start - 14 days`
- **Returns**:
  - `weight_diff`: Weight difference (kg)
  - `kcals_diff`: Calories difference
  - `water_diff`: Water intake difference (ml)
  - `sleep_diff`: Sleep hours difference
  - `tonnage_diff_by_muscle`: Tonnage change by muscle group
  - Plus current/previous values for each metric

#### 2. `/coach/stats/athlete/<athlete_id>/summary-28days.json`
- **Location**: Lines 1598-1723
- **Purpose**: Compare current week to week from 4 weeks ago
- **Comparison Date**: `current_week_start - 28 days`
- **Returns**: Same structure as 14-day endpoint

### Pattern Used
- Both endpoints follow the same structure as existing `summary-7days.json` endpoint
- Query journal entries for both weeks (current + comparison period)
- Query performance entries for tonnage calculations
- Calculate averages and differences
- Return JSON with all metrics

## Frontend Changes

### HTML (app/templates/coach_stats.html)
**Location**: Lines 88-155

Added two new card containers side-by-side:
1. **summary-14days-container** (Lines 92-130)
   - Displays: Weight, Kcals, Water, Sleep, Tonnage changes vs 2 weeks ago
   - IDs used:
     - `summary-14days-weight`
     - `summary-14days-kcals`
     - `summary-14days-water`
     - `summary-14days-sleep`
     - `summary-14days-tonnage-body` (table for muscle groups)

2. **summary-28days-container** (Lines 132-155)
   - Displays: Same metrics vs 4 weeks ago
   - IDs used:
     - `summary-28days-weight`
     - `summary-28days-kcals`
     - `summary-28days-water`
     - `summary-28days-sleep`
     - `summary-28days-tonnage-body` (table for muscle groups)

### JavaScript (app/static/js/coach_stats.js)

#### New Functions

1. **loadSummary14days(athleteId)** (Lines 264-329)
   - Fetches `/coach/stats/athlete/{athleteId}/summary-14days.json`
   - Formats and displays all metrics
   - Shows arrows indicating improvement (📈) or decline (📉)
   - Populates tonnage table by muscle group

2. **loadSummary28days(athleteId)** (Lines 331-396)
   - Fetches `/coach/stats/athlete/{athleteId}/summary-28days.json`
   - Same functionality as 14-day but for 4-week comparison
   - Shows arrows and tonnage changes

#### Function Integration (Line 707-709)
Added calls in athlete selection handler:
```javascript
await loadSummary(athleteId);
await loadSummary14days(athleteId);
await loadSummary28days(athleteId);
```

## Display Format

All summaries use consistent formatting:
- **📈** = Positive change (improvement)
- **📉** = Negative change (decline)
- **→** = Minimal change (< 0.1)
- **—** = No data available

### Metrics Displayed
- **Weight**: +/- kg (2 decimals)
- **Kcals**: +/- calories (whole numbers)
- **Water**: +/- ml (whole numbers)
- **Sleep**: +/- hours (1 decimal)
- **Tonnage**: By muscle group (whole numbers)

## Testing Checklist
- [ ] Select athlete → all three summaries load
- [ ] 7-day summary shows current vs previous week
- [ ] 14-day summary shows current vs 2 weeks ago
- [ ] 28-day summary shows current vs 4 weeks ago
- [ ] Tonnage differences display by muscle group
- [ ] Arrows show correct direction (📈 for gains, 📉 for losses)
- [ ] No data displays as "—"
- [ ] Page loads without JavaScript errors

## Dependencies
- Flask backend must have database populated with:
  - JournalEntry records
  - PerformanceEntry records
  - Exercise database with muscle groups
- Frontend requires: fetch API support

## Future Enhancements
- Chart visualizations for trend comparison
- Export functionality for summaries
- Date range selector for custom comparisons
- Historical graphs showing progression over multiple periods
