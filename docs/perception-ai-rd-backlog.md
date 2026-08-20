# Perception AI R&D Backlog

## Objective

Advance from frame-level object recognition toward a multimodal video-digestion system that can summarize behavior, motion, relationships, and event context across time windows. The long-term goal is a perception stack that understands not only what is visible, but also how entities move, relate, persist, and change over seconds, minutes, hours, and days.

## Strategic thesis

The current pipeline is strong as a first-pass detector and geospatial evidence engine, but it remains fundamentally object-centric. The next stage should be a temporally-aware, multi-scale perception model that compresses raw video into compact tokens and behavior summaries while preserving evidence frames for operator review.

This architecture should support:

- faster mission triage and event selection
- motion-aware object localization and re-identification
- contextual summaries for operator prompts and voice interfaces
- dynamic event retrieval from long historical footage
- multi-scale reasoning from short clips to daily patterns

## 1. Fast frontend perception

### Goal

Keep the front end cheap, sparse, and low-latency so it can act as a trigger and selector rather than a full expensive reasoner.

### Proposed components

- YOLO/instance-segmentation front end for boxes and masks
- plate-specific detector and vehicle instance segmentation pass
- simple scene prefilters to reject low-signal frames and low-motion areas
- ROI proposals for likely high-value detections only

### Design principles

- Every expensive step should be gated by cheap signals.
- Run OCR and complex feature extraction only on candidate ROIs.
- Use motion, priors, and confidence thresholds to reduce the number of slow paths.

## 2. Motion-aware object understanding

### Goal

Turn object recognition into object-state understanding by modeling movement, persistence, and interaction.

### Proposed methods

- SIFT / ORB / KLT tracklets for local motion estimation
- optical flow for short-window motion vectors
- segmentation + feature tracking for object continuity across frames
- object-state vectors: location, heading, velocity, persistence, scale change, and interaction pattern

### Why this matters

This improves geolocation, reduces false positives, and gives a better estimate of object intent and route behavior. It also helps separate a stationary object from a moving one, which matters for geospatial evidence and event interpretation.

## 3. Multi-scale tokenized video digestion

### Goal

Compress video into scene, object, and motion tokens instead of storing raw frames as the primary evidence substrate.

### Proposed pipeline

1. Extract frame embeddings or lightweight CNN/ViT features
2. Pool features into second-level summaries
3. Aggregate into minute/hour/day patterns
4. Store tokens in a vector database or a relational/event table for retrieval
5. Use token summaries for prompting, search, and behavior analysis

### Token types

- scene tokens
- object tokens
- motion tokens
- geospatial tokens
- mission metadata tokens
- event tokens

### Benefits

- efficient long-duration retrieval
- behavior summarization without scanning all raw footage
- compatibility with later prompt-driven operator interfaces and voice assistants
- stronger foundation for anomaly detection and evidence extraction

## 4. Temporal digest engine

### Goal

Summarize video at multiple time scales to enable event reasoning and contextual understanding.

### Example windows

- seconds: motion spikes, short interactions, micro-events
- minutes: route changes, loitering, repeated vehicle passes
- hours: dwell patterns, parking behavior, repeated access windows
- days: recurring activity, route associations, anomaly cycles

### Example derived insights

- suspicious loitering near a geofence
- repeated vehicle arrival patterns
- abnormal motion cluster in a restricted area
- object interactions that indicate aggression, pursuit, or evasive behavior

## 5. Memory optimization strategy

### Goal

Keep the system efficient enough to process persistent aerial footage without exhausting GPU or RAM.

### Techniques

- process sampled frames with adaptive frame_step
- downsample long clips for overview summarization
- keep only evidence frames for operator review
- extract candidate ROIs before OCR and deep-feature work
- use sparse tracklets instead of full dense motion estimation on every frame
- use temporal aggregation to avoid storing every frame-level embedding for long archives

## 6. Multimodal reasoning layer

### Goal

Provide an interface between perception, database summaries, and downstream reasoning systems.

### Proposed architecture

- perception layer: detectors, trackers, embeddings, motion models
- digest layer: temporal token summaries and event abstraction
- evidence layer: geospatial and mission metadata with confidence metadata
- reasoning layer: retrieval, prompt-driven summarization, operator copilots, alerts

### Example prompts

- “Show the high-risk events in this mission window.”
- “Summarize repeated vehicle movement near the south lot.”
- “Identify the candidate aggressor/victim cues from the interaction sequence.”
- “Find the frames supporting this geospatial anomaly.”

## 7. Research priorities for the next sprint

1. Add video metadata logging for duration, resolution, FPS, and frame count before processing.
2. Improve throughput by reducing OCR calls to only candidate plate ROIs.
3. Add SIFT/ORB/KLT motion feature tracking in the perception loop.
4. Evaluate lightweight embedding extraction for temporal event summaries.
5. Prototype a multi-scale token database for minutes/hours/days summaries.
6. Tie the digest layer to retrieval and operator-facing prompts.
7. Validate on real mission footage and record per-stage latency, confidence, and memory usage.

## 8. Guardrails

- Do not assume raw AI reasoning is sufficiently safe or lawful without evidence review and retention controls.
- Treat sensitive footage and geospatial evidence as restricted data.
- Keep operator review and explainability as required, not optional.
- Continue to prioritize modular, verifiable components over a monolithic black-box model.

## 9. Expected outcome

This roadmap moves the project from a basic object detector into a perception engine that can summarize long-form video, reason over behavior, improve geolocation, and produce a richer evidence stream for future voice-driven and prompt-driven intelligence workflows.
