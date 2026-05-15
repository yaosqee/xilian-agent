export interface AutonomyStatus {
  greeting_enabled: boolean;
  do_not_disturb: boolean;
  missing_value: number;
  threshold: number;
  bucket_tokens: number;
  bucket_capacity: number;
  pending_greeting: boolean;
}

export interface PendingGreeting {
  has_greeting: boolean;
  greeting: string | null;
  id: string | null;
}

export interface AutonomyConfig {
  greeting_enabled: boolean;
  greeting_threshold: number;
  greeting_max_per_hour: number;
  greeting_active_start: number;
  greeting_active_end: number;
  do_not_disturb: boolean;
  dnd_start: number;
  dnd_end: number;
}
