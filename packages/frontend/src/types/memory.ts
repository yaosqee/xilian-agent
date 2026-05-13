export interface MemoryItem {
  summary: string;
  distance: number;
  importance: number;
  episodic_id: number;
  timestamp: number;
}

export interface EncodingStatus {
  state: 'idle' | 'waiting' | 'encoding' | 'done';
  has_pending: boolean;
}
