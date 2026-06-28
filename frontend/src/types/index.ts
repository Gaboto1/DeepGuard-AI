export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed';
export type FileType = 'image' | 'video';
export type UncertaintyLevel = 'Baja' | 'Moderada' | 'Alta';

// Forensic evidence levels — replaces REAL/FAKE binary labels
export type EvidenceLevel =
  | 'Very Low Evidence'
  | 'Low Evidence'
  | 'Inconclusive'
  | 'Moderate Evidence'
  | 'Strong Evidence';

export type ModelAgreement = 'High Consensus' | 'Medium Consensus' | 'Low Consensus';

export interface ModelScore {
  name: string;
  score: number;       // 0–1
  weight: number;      // ensemble weight
  contribution: number; // weight × score
  score_pct: number;   // score × 100
}

export interface EnsembleBreakdown {
  models: ModelScore[];
  weights_mode: 'face_detected' | 'no_face';
  final_probability: number;
}

export interface OsintSearchLink {
  engine: string;
  url: string;
  note: string;
}

export interface OsintResult {
  status: string;
  note: string;
  search_links: OsintSearchLink[];
  perceptual_hash?: string | null;
  disclaimer: string;
}

export interface MetadataAnalysis {
  has_exif: boolean;
  camera_make?: string | null;
  camera_model?: string | null;
  software?: string | null;
  datetime_original?: string | null;
  gps_latitude?: number | null;
  gps_longitude?: number | null;
  color_space?: string | null;
  image_width?: number | null;
  image_height?: number | null;
  compression?: string | null;
  iso?: number | null;
  focal_length?: string | null;
  exposure_time?: string | null;
  f_number?: string | null;
  flash?: string | null;
  forensic_notes: string[];
}

export interface FrameResult {
  frame_index: number;
  timestamp: number;
  manipulation_probability: number;
  face_detected: boolean;
}

export interface SemanticAnalysis {
  risk_score: number;                      // 0-100
  risk_score_normalized: number | null;    // 0.0-1.0
  semantic_observations: string;
  model_used: string;
  quantization: string;
  analysis_time: number;
  fusion_type: string | null;              // semantic_blend | semantic_correction_up | semantic_correction_down | semantic_compression_zone
  fusion_note: string | null;
  available: boolean;
}

export interface TemporalAnalysis {
  temporal_anomaly_detected: boolean;
  temporal_consistency_score: number;      // 0-1
  temporal_discrepancy_values: number[];   // cosine distances
  temporal_variance: number;
  temporal_max_spike: number;
  optical_flow_values: number[];
  optical_flow_variance: number;
  optical_flow_anomaly: boolean;
  frames_with_faces: number;
  frames_analyzed: number;
  risk_multiplier: number;
  anomaly_details: string[];
  analysis_time: number;
}

// ── C2PA — Coalition for Content Provenance and Authenticity ──────────────────
export interface C2PAAction {
  action: string;
  when?: string | null;
  software_agent?: string;
}

export interface C2PAHistoryEntry {
  title: string;
  format?: string;
  relationship?: string;
  date?: string | null;
  tool?: string | null;
  actions: C2PAAction[];
}

export interface C2PAProvenance {
  has_c2pa: boolean;
  active: boolean;
  verified: boolean;
  signed_by?: string | null;
  claim_generator?: string | null;
  issued_at?: string | null;
  history_log: C2PAHistoryEntry[];
  error?: string | null;
}

export interface AnalysisResult {
  task_id: string;
  status: TaskStatus;
  file_type: FileType;
  filename: string;
  created_at: string;
  etapa?: string;   // etapa real del pipeline backend (en español), ej. "Ensemble 5 modelos"

  // Core forensic result
  manipulation_probability?: number;  // 0–100 for display
  evidence_level?: EvidenceLevel;
  model_agreement?: ModelAgreement;
  model_agreement_std?: number;
  explanation?: string;

  // Ensemble transparency
  ensemble?: EnsembleBreakdown | null;

  // Supporting evidence
  heatmap?: string | null;
  metadata_analysis?: MetadataAnalysis | null;
  osint?: OsintResult | null;

  // Analysis metadata
  analysis_time?: number;
  model_used?: string;
  device_used?: string;
  faces_detected?: number;

  // Video
  frames_analyzed?: number;
  video_duration?: number;
  frame_timeline?: FrameResult[];
  inconsistency_score?: number;

  // Análisis temporal (solo videos)
  temporal_analysis?: TemporalAnalysis | null;
  temporal_anomaly_detected?: boolean | null;

  // Uncertainty & OOD (v5.2)
  uncertainty?: UncertaintyLevel | null;
  uncertainty_score?: number | null;

  // OOD — Detección de diseño gráfico / afiche / texto denso
  is_ood?: boolean | null;
  ood_signal?: boolean | null;
  ood_confidence?: number | null;
  ood_score?: number | null;
  ood_signals?: string[] | null;

  risk_of_error?: string | null;
  ensemble_method?: string | null;

  // Cadena de custodia criptográfica (SHA-256 + HMAC-SHA256 v2)
  chain_of_custody?: {
    seal_version?:     string;
    task_id?:          string;
    file_sha256?:      string;
    filename?:         string;
    final_score?:      number;
    semantic_score?:   number;
    timestamp_utc?:    string;
    timestamp_unix?:   number;
    custody_token?:    string;
    canonical_string?: string;
    integrity_valid?:  boolean;
  } | null;

  // Análisis semántico VLM (LLaVA-1.5-7b-hf)
  semantic_analysis?: SemanticAnalysis | null;

  // Procedencia C2PA — Coalition for Content Provenance and Authenticity
  c2pa_provenance?: C2PAProvenance | null;

  progress: number;
  error?: string;
  completed_at?: string;

  // Backward compat — raw 0–1
  fake_probability?: number;
}

export interface UploadResponse {
  task_id: string;
  status: TaskStatus;
  message: string;
}

export interface HealthResponse {
  status: string;
  model_loaded: boolean;
  cuda_available: boolean;
  device: string;
  version: string;
}
