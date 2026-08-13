# Drone Unit Investment Memo

## Executive summary

This memo provides the investment logic for the drone hardware platform that underpins IntelSight’s geospatial intelligence product. The core recommendation is to treat the drone platform as a staged asset: first purchase a mature, proven consumer unit for field data collection and validation, then build a custom PX4-based platform only once the product economics and mission requirements are validated.

The project should not begin by buying a large, custom autonomous fleet platform before the team has demonstrated that the intelligence pipeline creates measurable value. The more disciplined path is to start with a low-risk field platform, confirm customer and operational demand, then invest in the higher-capability autonomous unit.

---

## 1. Investment objective

The goal is to purchase the lowest-cost hardware configuration that can:

- collect reliable telemetry and aerial footage
- generate a repeatable geospatial intelligence workflow
- validate detection, OCR, and geolocation performance
- support a credible path to autonomous live missioning later

The hardware should therefore be evaluated by:

- speed to field readiness
- operational reliability
- data quality
- ability to run future autonomous perception workloads
- cost per mission hour and cost per event captured
- path to scalable fleet operations

---

## 2. Unit economics lens

A drone unit is not just a tool; it is a revenue-generating asset. To justify the spend, it must either:

- lower the cost of operational coverage compared to manual methods
- increase evidence quality and mission throughput
- enable repeatable, automatable intelligence workflows
- support recurring subscription and service revenue

The unit economics should be measured by:

- cost per flight hour
- cost per valuable geospatial event
- mission turnaround time
- average data quality yield per mission
- labor cost saved or replaced by automation

---

## 3. Recommended platform path

### Phase 1: buy a verified commercial unit

Recommended option:

- DJI Mini 4 Pro as the primary validation and field data platform

Why:

- fast deployment
- lower risk
- reliable mission execution
- enough telemetry and image quality for early geospatial processing
- low upfront cost relative to a custom platform

This phase creates the strongest return on early investment because it reduces technology and integration risk while building the product foundation.

### Phase 2: build a custom PX4 mission platform

Recommended option:

- 7–8 inch PX4 multi-camera platform with Jetson companion compute

Why:

- true autonomous perception and custom sensing
- multi-view scanning without direct pointing
- open architecture for future fleet logic and edge AI
- better strategic control over product direction and system integration

This phase is justified only when the team has already validated the intelligence engine on the lower-risk platform.

---

## 4. Unit cost estimates

### A. Consumer-drone validation unit

| Component | Estimated cost (USD) | Purpose |
|---|---:|---|
| DJI Mini 4 Pro | $700–$1,200 | field data capture and validation |
| spare battery set | $100–$250 | mission repeatability |
| storage / SD cards | $30–$100 | flight data and imagery |
| processing laptop or workstation | $800–$2,000 | offline analytics |
| total | $1,630–$3,550 | practical low-risk validation stack |

### B. Prototype PX4 autonomous unit

| Component | Estimated cost (USD) | Purpose |
|---|---:|---|
| frame + motors + propellers + ESCs | $300–$700 | propulsion and structure |
| PX4 flight controller + GPS + compass | $250–$600 | control and navigation |
| companion computer | $500–$1,600 | autonomous perception and planning |
| 4–5 cameras + lenses | $500–$2,000 | multi-view collection |
| power system and batteries | $250–$700 | manage flight and payload power |
| telemetry and comms | $100–$500 | FC control and data relay |
| storage and cooling | $100–$500 | stable compute and recording |
| total | $2,000–$6,600 | realistic prototype range |

### C. Production fleet autonomous unit

| Component | Estimated cost (USD) | Purpose |
|---|---:|---|
| airframe and propulsion | $800–$2,000 | engineered fleet-grade platform |
| PX4 and peripherals | $400–$1,200 | dependable control stack |
| multi-camera payload | $1,000–$4,000 | side and forward perception |
| edge AI compute | $1,000–$3,500 | real-time analytics |
| RTK / mapping sensor stack | $300–$1,500 | geospatial precision |
| comms and safety systems | $400–$2,000 | operations and fleet readiness |
| total | $3,900–$14,200 | realistic production build |

---

## 5. Comparison with market alternatives

| Platform | Estimated unit cost | Strengths | Weaknesses | Strategic fit |
|---|---:|---|---|---|
| DJI Mini 4 Pro | $700–$1,200 | fast, reliable, proven | closed stack, limited autonomy | early validation |
| DJI Mavic 3 Enterprise | $2,000–$5,000 | better imaging and reliability | still not open enough for autonomous custom logic | field ops |
| Autel enterprise drones | $1,500–$4,000 | good imaging and operability | less open than PX4 | commercial mapping |
| Skydio enterprise drones | $8,000–$20,000+ | autonomy and obstacle avoidance | expensive and proprietary | premium enterprise automation |
| Custom PX4 prototype | $2,000–$6,600 | flexible, real autonomy, custom payloads | engineering risk | prototype and R&D |
| Production PX4 fleet platform | $4,000–$14,200 | strategic long-term platform | higher build and support cost | fleet-scale product |

### Key conclusion

The oral strategic message is clear: commercial drones are the right buy-now investment, while custom PX4 platforms are the right build-later investment.

---

## 6. Revenue support and return expectations

A drone hardware platform is a viable investment only when it supports repeatable, monetizable workflows. The strongest near-term revenue path for IntelSight is likely a hybrid model:

- service revenue from field data collection and intelligence reports
- subscription revenue for geospatial event tracking and intelligence dashboards
- project fees for geofenced monitoring, recurring scan missions, and analytics reports

A prototype or fleet unit becomes justified when it produces enough mission value to offset the per-unit hardware cost. The relevant KPI is not just hardware cost, but mission value per unit per month.

### Example operating value

A single drone unit can pay for itself faster when it reduces staff time, increases repeatable coverage, or creates recurring intelligence reports. The value is strongest in geofenced repeat-mission environments such as:

- parking lots
- commercial corridors
- resorts and hospitality campuses
- large industrial sites
- transport and logistics yards
- institutional or campus properties

---

## 7. Recommended buying policy

### Buy now

Buy a verified commercial platform if you need to:

- produce datasets quickly
- validate the product concept
- train the geospatial and detection pipeline
- run early pilots without major engineering risk
- shorten time to operational learning

### Build later

Build the PX4 platform if you need to:

- achieve live autonomous perception
- support custom sensors and multi-camera architecture
- create strategic control over software and mission logic
- support fleet-scale coordination
- build a defensible long-term product system

---

## 8. Final recommendation

The company should treat drone hardware as a staged investment portfolio:

1. First purchase a DJI-class consumer platform to validate the business and technical concept.
2. Then build a PX4 multi-camera unit to enable autonomous operational value.
3. Only scale to production fleet hardware after proving mission value and recurring demand.

This sequence creates a strong balance of:

- low upfront risk
- measurable product validation
- technical learning before scaling
- disciplined capital deployment
- a realistic path from prototype to fleet operations

In short: buy the proven unit to learn the market, build the custom platform to own the strategic layer.
