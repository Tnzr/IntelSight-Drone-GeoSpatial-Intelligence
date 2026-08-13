# PX4 Multi-Camera Perception Platform

## Executive recommendation

The recommended improvement is to move beyond a single forward-facing payload and build a multi-lateral perception stack on the PX4 platform. The goal is not to make the drone look suspicious by aiming directly at a target, but to maintain a realistic, low-profile flight posture while still collecting strong contextual visual information from the side streets, parking lanes, driveways, and perimeter zones.

This design is especially useful for:

- lane and street scanning without pointing the drone directly at a target
- object acquisition from oblique, non-threatening angles
- reducing social and operational alarm risk from a single front-facing camera
- building contextual geospatial evidence with repeated side-angle observations
- supporting later deblurring and multi-view fusion techniques

The system should use a mixed camera strategy:

- 1 forward camera for primary path observation and route tracking
- 2 lateral cameras, one on each side, for street-level and parking-lot scanning
- 1 rear camera for corridor awareness, safe retreat, and event correlation
- optional downward camera for georeferencing, terrain tracking, and map alignment

A fifth or 360-degree approach may be added later, but the first practical version should remain lightweight and reliable.

---

## Strategy: stealthy, distributed perception

The direct-camera approach can be problematic because it creates a more obvious threat perception: a drone pointed directly at a person or vehicle in a neighborhood often feels aggressive or suspicious. A lateral-perception layout is more natural in the field because it keeps the drone in a persistent, routine flight pattern while the optical system scans adjacent objects from off-axis angles.

The operational logic should be:

- front camera: primary flight and obstacle awareness
- left/right cameras: side-scanning, parking-lot and curb surveillance, vehicle association
- rear camera: reverse and perimeter awareness
- downward camera: georeferencing and terrain motion estimation

This arrangement is especially effective when combined with:

- multi-frame tracking
- cross-camera association
- deblurring and super-resolution at lower speeds
- geofence-based mission logic

---

## Platform comparison: DJI Mini 4 Pro vs custom PX4

| Category | DJI Mini 4 Pro | Custom PX4 platform | Assessment |
|---|---|---|---|
| Live autonomy | Limited, closed ecosystem | Full custom autonomy possible | PX4 wins |
| Sensor expansion | Very limited | High flexibility | PX4 wins |
| Multi-lateral camera support | Poor | Excellent | PX4 wins |
| Flight control openness | Closed | Open and tunable | PX4 wins |
| Time to first field data | Very fast | Slower | DJI wins |
| Operational reliability | Excellent | Requires tuning and validation | DJI wins |
| Custom payload design | Weak | Strong | PX4 wins |
| Perception-in-flight | Hard | Strong | PX4 wins |
| Data collection accuracy | Good | Good to excellent with calibrated sensors | Depends on build |
| Cost to prototype | Lower | Higher | DJI wins |
| Long-term platform strategy | Good for phase 1 | Best for phase 2+ | PX4 wins |

### Takeaway

For a stealth multi-camera payload, the PX4 route is strongly preferred. The DJI platform is excellent as a collection and validation platform, but it is not the ideal platform for a custom multi-view, low-profile, autonomous perception machine.

---

## Recommended hardware architecture

### 1. Frame and airframe

Recommended start point:

- 7-inch or 8-inch carbon fiber quadcopter frame
- sturdy center plate for mounting 4 to 5 camera modules
- vibration-isolated camera rails or dampers
- compact shape for lower wind resistance and stealthy profile

Suggested frame types:

- 7-inch freestyle / mapping hybrid
- 8-inch endurance frame for payload and battery efficiency
- 10-inch if heavier payload and longer flight time are more valuable than maneuverability

Why this matters:

- more payload headroom for side and rear cameras
- less strain on the motors and ESCs
- easier to mount optics without compromising center-of-gravity alignment

### 2. Flight controller and autopilot

Recommended options:

- Pixhawk 6X or a similar PX4-compatible controller
- Cube Orange / Cube Black for more industrial setups
- Holybro or similar quality stack with proven PX4 integration

Recommended features:

- PX4-native support
- robust IMU / barometer / magnetometer stack
- GPS + compass redundancy where possible
- good hardware vibration isolation

### 3. Companion computer

Recommended options:

- NVIDIA Jetson Orin Nano 8GB for serious onboard vision
- NVIDIA Jetson Xavier NX for a proven edge-AI stack
- Raspberry Pi 5 only if the AI pipeline is lighter and the architecture stays modest

Why this matters:

- the multi-camera arrangement creates more inference and synchronization work
- a proper companion computer is needed for coordinated camera fusion and object tracking
- offline or real-time route logic is much easier to implement with a standard Linux stack and ROS2

### 4. Cameras

The cameras should be chosen for the operational goal: low-profile, non-intimidating perception, good motion performance, and enough quality for deblurring and cross-view alignment.

#### Recommended camera arrangement

- Front: 4K or 1080p high-quality RGB camera, 30–60 fps
- Left: 1080p/60 or 4K/30 with a wide-angle lens, mounted 30–45 degrees off-axis
- Right: same as left
- Rear: 1080p/30 or 60 for safety and tactical awareness
- Downward: 1080p/30 or 60 global-shutter or high-quality rolling-shutter option for terrain alignments

#### Camera class recommendation

For the first practical build, prioritize:

- good low-light performance
- strong rolling shutter stability at moderate flight speeds
- high enough frame rate for multi-frame deblurring
- a wide field of view for side scanning without direct pointing

Prefer:

- USB 3.0 industrial cameras or compact machine-vision cams
- Sony IMX sensors or similar mid-range industrial optics
- lenses in the 80–120 degree FOV range for side views
- fixed 30–45 degree off-axis mounts rather than extreme fisheye setups

Avoid for phase 1:

- extremely cheap security webcams with severe rolling shutter artifacts
- very low FPS cameras that make motion compensation unreliable
- ultra-wide lenses that distort vehicle shape beyond usable OCR or detection ranges

---

## Example parts list for a realistic build

### Core airframe and flight control

| Part | Suggested type | Purpose | Notes |
|---|---|---|---|
| Frame | 7-inch or 8-inch carbon fiber quad | main aircraft structure | better payload capacity and stability |
| Motors | 2807 / 3008 class brushless motors | propulsion | choose according to payload and battery |
| Propellers | 7x3.5 or 8x4.5 | thrust and efficiency | tune for payload and endurance |
| ESCs | 40A–60A BLHeli32 or equivalent | motor control | good telemetry and safety |
| Flight controller | Pixhawk 6X / Cube Orange | autopilot | best fit for PX4 |
| GPS | M10 / RTK-capable GPS | precision tracking | useful for mapping and later georectification |
| Compass | integrated or external | heading accuracy | essential for lateral perception calibration |
| Power module | 12S/6S compatible power distribution | power routing | depends on selected system |

### Companion compute and perception

| Part | Suggested type | Purpose | Notes |
|---|---|---|---|
| Companion computer | Jetson Orin Nano / Xavier NX | onboard inference | needed for multi-camera vision |
| Storage | NVMe SSD or high-speed microSD | image/video + logs | reduces IO bottlenecks |
| Network | USB 3 / gigabit Ethernet | sensor sync | keeps camera data stable |
| IMU | on-board flight controller plus external IMU if needed | fusion and control | improves pose stability |

### Camera payload

| Part | Suggested type | Purpose | Notes |
|---|---|---|---|
| Front camera | 4K/30 or 1080p/60 IP/USB camera | path awareness | high fidelity for primary detection |
| Side camera x2 | 1080p/60 or 4K/30 wide lens | lateral scan | preserve low-profile visual collection |
| Rear camera | 1080p/30 or 60 | rear awareness | safety and event correlation |
| Downward camera | 1080p/60 or global-shutter if possible | georeferencing and terrain tracking | key for map alignment |
| Lenses | 80–120 degree FOV | wide coverage | prefer balanced distortion |
| Camera mounts | vibration-isolated and off-axis | reduce shock and camera misalignment | important for deblurring |

### Communication and system integration

| Part | Suggested type | Purpose | Notes |
|---|---|---|---|
| Telemetry radio | 915/868 MHz or appropriate telemetry module | FC to ground control | standard PX4 setup |
| Long-range comms | Wi-Fi HaLow or other long-range link | telemetry and control extension | useful for later fleet use |
| Video link | 5.8GHz or other suitable datalink | live visual feed | optional, not required for all phase-1 work |
| Ground station | laptop or rugged PC | mission planning and analysis | needed for field deployment |

### Power and support

| Part | Suggested type | Purpose | Notes |
|---|---|---|---|
| Battery | 6S 5000–8000 mAh | power | choose for target endurance |
| UBEC or power regulator | 12V/5V converter | camera and compute power | critical for clean power |
| Cooling | passive or active | companion computer thermals | Jetson can get hot under load |
| Fasteners / rails | vibration damping hardware | stability and reliability | important for camera calibration |

---

## Deblurring and motion constraints

For reasonable flight speeds, the cameras need to be able to be used with deblurring techniques. That means the payload should support:

- at least 30–60 fps capture on the active cameras
- short shutter exposure, ideally around 1/500 to 1/1000 for faster motion scenarios when possible
- good synchronization across cameras when multi-view fusion is used
- enough frame overlap to support motion estimation and deblurring between consecutive frames

The best first-pass design is not necessarily a 360-degree camera rig. A 4-camera layout with side coverage and a forward path camera is much more realistic and operationally useful. A 360 rig is still possible later, but it introduces synchronization, calibration, and computational overhead that can be too heavy for an initial field prototype.

---

## Why this is a better system than a single forward camera

A single front-facing camera is simpler, but it creates several practical issues:

- direct looking at targets increases perception of threat or intrusion
- poor coverage of side streets and curb-adjacent objects
- incomplete contextual observation of adjacent lots or driveways
- inconsistent event capture when the drone is following a route pattern

The side-lateral camera arrangement solves these by creating a steady, low-profile scan pattern along roads, parking lots, and property edges while the drone remains in a normal mission posture.

This also fits the geospatial approach better:

- side-angle detections can be matched to the same asset or vehicle from multiple frames
- multi-view correlation improves spatial confidence
- repeated observations create better historical association data

---

## Recommended first build configuration

For the first real autonomous build, use this configuration:

- 1 forward camera
- 2 lateral cameras
- 1 rear camera
- 1 downward camera
- PX4 autopilot
- Jetson Orin Nano / Xavier NX
- 7–8 inch carbon fiber quad with payload allowance
- 6S battery with good endurance margin
- telem + high-quality route logic

This is the best compromise between stealth, practicality, and field usefulness.

A 360 camera system may be added later as a second-stage enhancement after:

- the mission logic is validated
- the synchronization pipeline is stable
- the deblurring and fusion workflow is proven

---

## BOM and cost analysis

The key strategic decision is not only technical capability, but the cost per unit and the revenue model that can support it. Below is a realistic bill of materials for a production-minded prototype and a comparison against factory drones.

### 1. Cost tiers

#### Tier A: Low-cost field validation platform

This is the best option for the first 6–12 months while the team validates detection, georeferencing, and analytics workflows.

| Component | Approx. cost (USD) | Notes |
|---|---:|---|
| DJI Mini 4 Pro with RC 2 or RC-N2 support path | $700–$1,200 | Use for field data capture and workflow validation |
| Spare batteries | $100–$250 | critical for repeated mission testing |
| SD cards / storage | $30–$100 | depends on field data volume |
| basic compute / laptop | $800–$2,000 | used for offline processing |
| total | $1,600–$3,550 | fast, low-risk startup stack |

This tier is ideal when the company is still validating the data pipeline and geospatial intelligence value.

#### Tier B: Research and prototype PX4 autonomous platform

This is the first serious custom build for multi-camera and live autonomy experiments.

| Component | Approx. cost (USD) | Notes |
|---|---:|---|
| 7-inch or 8-inch carbon frame | $120–$250 | durable payload-ready frame |
| motors, ESCs, props | $200–$500 | depends on power and endurance target |
| PX4 flight controller + GPS / compass | $250–$600 | Pixhawk 6X or similar |
| companion computer | $500–$1,600 | Jetson Orin Nano / Xavier NX |
| 4–5 cameras + lenses | $500–$2,000 | side, front, rear, down, plus optics |
| power distribution + battery + regulators | $250–$700 | critical for clean integration |
| telemetry and comms | $100–$500 | telemetry radio and optional long-range link |
| storage + cooling | $100–$500 | for image capture and compute stability |
| total | $2,120–$6,650 | practical prototype cost range |

This tier is still manageable for a focused prototype program and is the right level when moving from offline to live autonomy.

#### Tier C: production-ready fleet platform

This is the platform class if the system becomes a fleet-capable operational product.

| Component | Approx. cost (USD) | Notes |
|---|---:|---|
| airframe + propulsion + FC | $800–$2,000 | optimized for industrial use |
| multi-camera payload | $1,000–$4,000 | tuned for side scanning and object detection |
| companion compute | $1,000–$3,500 | edge-AI compute, storage, thermal design |
| RTK / mapping sensors | $300–$1,500 | adds geospatial precision |
| radio and fleet comms | $400–$2,000 | telemetry, operator link, optional HaLow |
| safety / redundancy hardware | $300–$1,500 | spare sensors and protection |
| total per drone | $3,800–$14,500 | realistic deployed unit cost |

This is the range for a real high-value operational fleet, not a hobby prototype.

---

### 2. Comparison against factory drones

| Platform | Typical purchase range | Pros | Cons | Strategic use |
|---|---:|---|---|---|
| DJI Mini 4 Pro | $700–$1,200 | polished, reliable, fast field data, easy to deploy | closed ecosystem, limited autonomy | rapid validation and offline mapping |
| DJI Mavic 3 Enterprise | $2,000–$5,000 | better ruggedness and payload options | still limited custom autonomy | commercial inspection and mapping |
| Autel EVO II / enterprise lines | $1,500–$4,000 | good flight quality, strong optics | less open ecosystem than full PX4 | quick capture workflows |
| Skydio X10 / enterprise autonomy drones | $8,000–$20,000+ | strong autonomy, obstacle avoidance | premium pricing, proprietary stack | premium industrial use cases |
| Custom PX4 prototype | $2,000–$6,500 prototype | full control, custom cameras, autonomous logic | tuning, build risk, more engineering effort | long-term autonomy and custom fleet |
| Production PX4 fleet platform | $4,000–$15,000+ | custom payload, vehicle integration, fleet control | higher engineering and maintenance costs | strategic autonomous platform |

### Interpretation

- If the immediate goal is data collection, DJI is the cheapest and fastest route.
- If the long-term goal is autonomous perception with custom multi-camera sensing, the PX4 path wins on capability and strategic control.
- For a company building an actual product, a balanced path is to buy a factory drone for early validation and then build a custom platform only after the system is proven.

---

### 3. Recommended suppliers

#### Consumer / field deployment platforms

- DJI: best for direct-field validation and flight reliability
- Autel Robotics: strong alternative for enterprise imaging and mapping
- Skydio: strong autonomy-first ecosystem, but premium priced

#### Open hardware / PX4 component ecosystem

- Holybro: one of the strongest PX4-integrated hardware portfolios
- Pixhawk ecosystem suppliers: standard PX4-compatible FCUs and modules
- NVIDIA: Jetson Orin Nano / Xavier NX for onboard inference
- Raspberry Pi: only viable for lighter workloads or secondary processing 
- Amazon, Digi-Key, Mouser, and SparkFun: core electronics and sensors
- FRAMOS, Basler, or industrial USB camera suppliers: for higher-quality machine vision payloads
- Lumenier, T-Motor, and HobbyKing-style vendors: for motors, props, and support gear, depending on region and sourcing risk

#### Camera and vision hardware

- Basler
- e-con Systems
- Leopard Imaging
- Arducam
- Sony IMX sensor-based USB camera vendors
- industrial machine-vision suppliers for calibration-friendly, low-latency sensors

### Supplier recommendation by phase

- Phase 1: purchase DJI or Autel for immediate field collection
- Phase 2: buy Holybro / Pixhawk ecosystem parts for PX4 airframe and flight stack
- Phase 3: buy NVIDIA Jetson modules and industrial cameras for edge-AI payloads

---

### 4. Revenue model and investment impact

The relevant business question is simple: what unit cost can the company support while still generating a healthy margin?

#### Example revenue model assumptions

- project-based drone data collection: $2,000–$10,000 per mission or engagement
- recurring fleet intelligence subscription: $500–$5,000/month per client or site
- AI analytics service: $150–$1,500 per site or per processing batch
- custom field support and reporting: $1,000–$10,000 per project

#### Investment logic

- A DJI-based validation platform can be purchased for roughly $1,500–$4,000 and is a low-risk business investment.
- A PX4 prototype can be built for roughly $2,000–$7,000 and is a reasonable R&D investment if the product path is credible.
- A production fleet drone may cost $4,000–$15,000 per unit, but it is justified only when there is recurring operational value and enough mission volume to monetize it.

The key metric is not just purchase price, but cost per observed event, cost per mission hour, and the repeatability of the service model.

---

### 5. Buy now / build later recommendation

#### Buy now

Buy a DJI Mini 4 Pro or a similar verified commercial drone if you need to:

- establish the data pipeline immediately
- validate geotagging and georeferencing
- prove the object detection and OCR pipeline in the field
- create a serviceable dataset quickly
- reduce product risk before committing to custom hardware

This is the right business move for the first year.

#### Build later

Build the custom PX4 multi-camera platform when you need to:

- run live autonomous perception on-board
- support multi-angle scanning without direct pointing
- integrate multi-camera fusion and deblurring
- support fleet-level mission coordination
- create a true strategic platform rather than a data-collection drone

This is the right hardware move for phase 2 and beyond.

### Final buy-now / build-later decision

For this project, the recommendation is:

- buy a DJI Mini 4 Pro now for Phase 1 execution and validation
- build a custom PX4 side-scanning multi-camera drone next for autonomous live perception
- avoid a full 360-degree gimbal or camera array before the core mission logic and deblurring pipeline is proven

This sequence minimizes upfront risk while preserving the path to the autonomous fleet platform.

---

## Final recommendation

The strongest platform decision for this project is:

- keep the DJI Mini 4 Pro for phase 1 validation and offline intelligence work
- build a custom PX4 multi-camera system for the autonomous perception layer
- use a side-scanning camera array instead of a single pointed camera to reduce suspicious behavior and improve street-level coverage
- prioritize robust optics, motion handling, and data synchronization before expanding to a full 360-degree system
- maintain a modular BOM strategy that allows the team to start on a lower-cost validation platform and then graduate to a production autonomous airframe when the revenue case is proven

This architecture gives the project the best balance of stealth, mission realism, perception capacity, cost control, and future scalability.
