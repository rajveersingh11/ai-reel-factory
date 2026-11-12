"""
AI Reel Factory — Human Review & Publishing Dashboard
====================================================
Streamlit-based local UI for:
  - Multi-brand Job Management (SKYON, R4Realty, etc.)
  - Gate 1: Human Script Review, Editing & Regeneration
  - Gate 2: Rendered Reel Video Playback & Deterministic QC Inspection
  - One-Click Instagram Reels Distribution with AI Transparency Disclosure
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
import streamlit as st

# Configure page layout
st.set_page_config(
    page_title="AI Reel Factory — Studio Dashboard",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

from src.core.config import settings
from src.core.database import SessionLocal, init_db
from src.models.job import Job, JobStatus
from src.schemas.brand import BrandRegistry
from src.services.publishing.instagram import InstagramPublisher
from src.workers.tasks import execute_job_pipeline

# Ensure DB tables exist
init_db()

# Load brand registry
registry = BrandRegistry()
all_brands = registry.list_brands()
brand_map = {b.id: b for b in all_brands}


def get_db():
    return SessionLocal()


# -----------------------------------------------------------------------------
# SIDEBAR: Multi-Brand Controls & Job Creation
# -----------------------------------------------------------------------------
st.sidebar.title("🎬 AI Reel Factory")
st.sidebar.caption("Local-First 9:16 Short-Form Video Engine")

selected_brand_id = st.sidebar.selectbox(
    "Select Brand Profile",
    options=["all"] + [b.id for b in all_brands],
    format_func=lambda x: "All Brands" if x == "all" else f"{brand_map[x].name} ({x})",
)

st.sidebar.markdown("---")
st.sidebar.subheader("➕ Create New Reel Job")
with st.sidebar.form("new_job_form", clear_on_submit=True):
    job_brand = st.selectbox(
        "Brand",
        options=[b.id for b in all_brands],
        format_func=lambda x: brand_map[x].name,
    )
    suggested_topics = brand_map[job_brand].topics if job_brand in brand_map else []
    topic_suggestion = st.selectbox("Topic Ideas (Optional)", ["Custom..."] + suggested_topics)
    default_topic = "" if topic_suggestion == "Custom..." else topic_suggestion
    job_topic = st.text_area("Video Topic / Headline", value=default_topic, height=80)
    submitted = st.form_submit_button("Queue Production", use_container_width=True)

    if submitted:
        if len(job_topic.strip()) < 5:
            st.sidebar.error("Topic must be at least 5 characters.")
        else:
            db = get_db()
            new_job = Job(
                brand_id=job_brand,
                topic=job_topic.strip(),
                status=JobStatus.PENDING,
                stage="queued",
            )
            db.add(new_job)
            db.commit()
            db.refresh(new_job)
            db.close()
            st.sidebar.success(f"Job queued! ID: {new_job.id[:8]}")
            st.rerun()

st.sidebar.markdown("---")
status_filter = st.sidebar.selectbox(
    "Filter by Status",
    options=["ALL", "SCRIPT_APPROVAL_PENDING", "FINAL_APPROVAL_PENDING", "PUBLISHED", "COMPLETED", "REJECTED"],
)

if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
    st.rerun()


# -----------------------------------------------------------------------------
# MAIN DASHBOARD: Metrics & Job Selection
# -----------------------------------------------------------------------------
db = get_db()
query = db.query(Job)
if selected_brand_id != "all":
    query = query.filter(Job.brand_id == selected_brand_id)

if status_filter != "ALL":
    query = query.filter(Job.status == getattr(JobStatus, status_filter))

jobs = query.order_by(Job.created_at.desc()).limit(50).all()

# Metrics row
total_jobs = db.query(Job).count()
gate1_pending = db.query(Job).filter(Job.status == JobStatus.SCRIPT_APPROVAL_PENDING).count()
gate2_pending = db.query(Job).filter(Job.status == JobStatus.FINAL_APPROVAL_PENDING).count()
published_count = db.query(Job).filter(Job.status == JobStatus.PUBLISHED).count()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Jobs", total_jobs)
col2.metric("Gate 1 Pending (Scripts)", gate1_pending)
col3.metric("Gate 2 Pending (Videos)", gate2_pending)
col4.metric("Published Reels", published_count)

st.markdown("---")

if not jobs:
    st.info("No video production jobs found matching the selected filter. Create one from the sidebar!")
    db.close()
    st.stop()

# Job selection dropdown
job_options = {
    f"[{j.brand_id.upper()}] {j.topic[:45]}... | {j.status.value} ({j.id[:8]})": j.id
    for j in jobs
}
selected_label = st.selectbox("Select Job to Inspect & Review", list(job_options.keys()))
active_job_id = job_options[selected_label]
job = db.query(Job).filter(Job.id == active_job_id).first()

if not job:
    st.error("Job record not found.")
    db.close()
    st.stop()

# Display active job metadata banner
brand = brand_map.get(job.brand_id)
brand_name = brand.name if brand else job.brand_id.upper()

st.subheader(f"📌 {job.topic}")
b_col1, b_col2, b_col3, b_col4 = st.columns(4)
b_col1.markdown(f"**Brand:** `{brand_name}`")
b_col2.markdown(f"**Status:** `{job.status.value}`")
b_col3.markdown(f"**Stage:** `{job.stage}`")
b_col4.markdown(f"**Created:** `{job.created_at.strftime('%Y-%m-%d %H:%M')}`")

st.markdown("---")

# Main Action Tabs
tab_script, tab_video, tab_publish = st.tabs([
    "📝 Gate 1: Script Review",
    "🎥 Gate 2: Video & QC Preview",
    "🚀 Social Distribution (Instagram)",
])


# -----------------------------------------------------------------------------
# TAB 1: Gate 1 Script Review
# -----------------------------------------------------------------------------
with tab_script:
    st.markdown("### Script Intelligence & Fact Verification")
    script = job.script_data or {}

    if not script:
        st.warning("Script data has not been generated yet for this job.")
        if job.status == JobStatus.PENDING:
            if st.button("⚡ Run Pipeline Now (Research & Scripting)"):
                with st.spinner("Executing pipeline in background..."):
                    execute_job_pipeline(job.id)
                st.success("Pipeline executed!")
                st.rerun()
    else:
        # Script Metadata
        words = script.get("total_words", 0)
        est_sec = script.get("estimated_duration_sec", 0.0)
        facts = script.get("verified_facts", [])

        sc_col1, sc_col2, sc_col3 = st.columns(3)
        sc_col1.metric("Word Count", words, "145–160 target")
        sc_col2.metric("Est. Duration", f"{est_sec:.1f}s", "55–65s target")
        sc_col3.metric("Verified Facts", len(facts))

        # Check for unbacked claims
        scenes = script.get("scenes", [])
        flagged_scenes = [s for s in scenes if s.get("is_flagged", False)]
        if flagged_scenes:
            st.warning(
                f"⚠️ Fact-Check Alert: {len(flagged_scenes)} scene(s) contain unbacked numeric claims! "
                f"Verify or edit before approving."
            )

        st.markdown(f"**Opening Hook:**")
        st.info(script.get("hook", ""))

        st.markdown("**Scenes Breakdown:**")
        for sc in scenes:
            with st.expander(f"Scene {sc.get('scene_number', 1)}: {sc.get('visual_concept', '')[:50]}...", expanded=True):
                st.markdown(f"🗣️ **Narration:** {sc.get('narration_text', '')}")
                st.caption(f"🎨 **Visual Prompt:** {sc.get('visual_concept', '')}")
                metric = sc.get("statistic_metric")
                if metric:
                    st.markdown(f"📊 **Stat Callout:** `{metric}` (Source: `{sc.get('source_citation', 'N/A')}`)")
                if sc.get("is_flagged"):
                    st.error("🚩 Unbacked numeric claim detected in this scene.")

        st.markdown(f"**Call to Action:** `{script.get('call_to_action', '')}`")

        # Gate 1 Decision Controls
        st.markdown("---")
        st.subheader("Gate 1 Decision Controls")

        g1_col1, g1_col2, g1_col3, g1_col4 = st.columns(4)

        with g1_col1:
            if st.button("✅ Approve Script", type="primary", use_container_width=True):
                job.status = JobStatus.APPROVED
                job.stage = "script_approved"
                db.commit()
                st.success("Script approved! Triggering video production...")
                with st.spinner("Rendering multi-clip 1080x1920 Reel with subtitles..."):
                    execute_job_pipeline(job.id)
                st.rerun()

        with g1_col2:
            with st.popover("✏️ Edit Script"):
                st.write("Edit narration text:")
                new_hook = st.text_area("Hook", script.get("hook", ""))
                new_cta = st.text_area("CTA", script.get("call_to_action", ""))
                if st.button("Save Edited Script"):
                    script["hook"] = new_hook
                    script["call_to_action"] = new_cta
                    job.script_data = script
                    job.status = JobStatus.APPROVED
                    db.commit()
                    st.success("Saved & approved!")
                    st.rerun()

        with g1_col3:
            with st.popover("🔄 Regenerate"):
                regen_feedback = st.text_input("Feedback prompt", placeholder="e.g. Make hook punchier")
                if st.button("Trigger Regeneration"):
                    from src.services.llm.script_generator import ScriptGenerator
                    gen = ScriptGenerator()
                    new_script = gen.generate_script(job.topic, brand_map[job.brand_id], feedback=regen_feedback)
                    job.script_data = new_script.model_dump()
                    job.status = JobStatus.SCRIPT_APPROVAL_PENDING
                    db.commit()
                    st.success("Regenerated version created!")
                    st.rerun()

        with g1_col4:
            if st.button("❌ Reject Script", use_container_width=True):
                job.status = JobStatus.REJECTED
                job.stage = "rejected_at_script_review"
                db.commit()
                st.error("Job rejected.")
                st.rerun()


# -----------------------------------------------------------------------------
# TAB 2: Gate 2 Video & QC Inspection
# -----------------------------------------------------------------------------
with tab_video:
    st.markdown("### Rendered Video Preview & Deterministic QC Inspection")

    if not job.video_path or not Path(job.video_path).exists():
        st.info("No rendered video exists yet. Approve the script in Gate 1 to render.")
    else:
        v_col1, v_col2 = st.columns([1, 1])

        with v_col1:
            st.markdown("#### 📱 9:16 Vertical Reel Player")
            st.video(job.video_path)
            st.caption(f"📁 Video Path: `{job.video_path}`")

        with v_col2:
            st.markdown("#### 🔍 Deterministic QC Report")
            qc = job.qc_report or {}
            passed = qc.get("all_passed", False)

            if passed:
                st.success("🎯 ALL QC CHECKS PASSED — READY FOR SOCIAL PUBLISHING")
            else:
                st.error("⚠️ QC CHECKS FAILED OR INCOMPLETE")

            # QC checklist
            checks = qc.get("checks", {})
            st.checkbox("Resolution: 1080x1920 (9:16)", value=checks.get("resolution", False), disabled=True)
            st.checkbox("Duration: 55.0s – 65.0s", value=checks.get("duration", False), disabled=True)
            st.checkbox("Loudness: -14 LUFS target", value=checks.get("loudness", False), disabled=True)
            st.checkbox("Silence: No gap > 1.5s", value=checks.get("silence", False), disabled=True)
            st.checkbox("Moov Faststart (Web Optimized)", value=checks.get("faststart", False), disabled=True)

            with st.expander("View Full ffprobe & EBU R128 Data"):
                st.json(qc)

            st.markdown("---")
            st.subheader("Gate 2 Decision")
            g2_col1, g2_col2 = st.columns(2)

            with g2_col1:
                if st.button("✅ Approve Video for Publishing", type="primary", use_container_width=True):
                    job.status = JobStatus.COMPLETED
                    job.stage = "approved_for_publishing"
                    db.commit()
                    st.success("Final video approved! Ready for Instagram distribution.")
                    st.rerun()

            with g2_col2:
                if st.button("❌ Reject Video", use_container_width=True):
                    job.status = JobStatus.REJECTED
                    job.stage = "rejected_at_final_approval"
                    db.commit()
                    st.error("Video rejected by reviewer.")
                    st.rerun()


# -----------------------------------------------------------------------------
# TAB 3: Social Publishing (Instagram Reels)
# -----------------------------------------------------------------------------
with tab_publish:
    st.markdown("### Instagram Reels Distribution (Meta Graph API v21.0)")

    if job.status == JobStatus.PUBLISHED:
        st.success("🎉 THIS REEL HAS BEEN PUBLISHED TO INSTAGRAM!")
        p_col1, p_col2 = st.columns(2)
        p_col1.markdown(f"**Instagram Media ID:** `{job.instagram_media_id}`")
        if job.instagram_permalink:
            p_col2.markdown(f"**Permalink:** [View Reel on Instagram]({job.instagram_permalink})")
        if job.published_at:
            st.caption(f"Published at: {job.published_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    else:
        is_ready = job.status == JobStatus.COMPLETED or job.stage == "approved_for_publishing"

        if not is_ready:
            st.warning("⚠️ Gate 2 video approval is required before this video can be published.")
        else:
            publisher = InstagramPublisher()
            default_caption = publisher._format_caption(job)

            st.markdown("#### Post Caption & AI Transparency Compliance")
            custom_caption = st.text_area("Caption (includes mandatory #AIgenerated tag)", value=default_caption, height=180)

            st.info("ℹ️ Mode: Meta Graph API (Simulated/Mock fallback active when token is unset).")

            if st.button("🚀 Publish to Instagram Reels Now", type="primary", use_container_width=True):
                with st.spinner("Contacting Meta Graph API and uploading Reel..."):
                    try:
                        res = publisher.publish_reel(
                            job=job,
                            db=db,
                            caption=custom_caption,
                        )
                        st.success(f"Successfully published! Media ID: {res.get('instagram_media_id')}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Publishing failed: {e}")

db.close()

