import { useEffect, useRef } from 'react';
import { Mic, Square, AlertCircle } from 'lucide-react';
import { useVoiceRecorder } from '../hooks/useVoiceRecorder';

interface VoiceRecorderProps {
  onRecordingComplete: (blob: Blob) => void;
  disabled?: boolean;
  maxDuration?: number;
}

export default function VoiceRecorder({ onRecordingComplete, disabled = false, maxDuration = 30 }: VoiceRecorderProps) {
  const { isRecording, isSupported, duration, audioBlob, startRecording, stopRecording, cancelRecording, error } = useVoiceRecorder();
  const onCompleteRef = useRef(onRecordingComplete);
  const deliveredBlobRef = useRef<Blob | null>(null);

  useEffect(() => {
    onCompleteRef.current = onRecordingComplete;
  }, [onRecordingComplete]);

  useEffect(() => {
    if (isRecording && duration >= maxDuration) {
      stopRecording();
    }
  }, [duration, isRecording, maxDuration, stopRecording]);

  useEffect(() => {
    if (audioBlob && deliveredBlobRef.current !== audioBlob) {
      deliveredBlobRef.current = audioBlob;
      onCompleteRef.current(audioBlob);
    }
  }, [audioBlob]);

  if (!isSupported) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-400">
        <AlertCircle className="w-4 h-4" />
        Voice not supported
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3">
      {error && (
        <span className="text-sm text-red-500">{error}</span>
      )}

      {isRecording ? (
        <>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
            <span className="text-sm text-red-500 font-mono">{duration}s</span>
          </div>
          <button
            onClick={() => {
              stopRecording();
            }}
            disabled={disabled}
            className="flex items-center gap-1 px-3 py-1.5 bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:opacity-50 text-sm"
          >
            <Square className="w-3.5 h-3.5" />
            Stop
          </button>
          <button
            onClick={cancelRecording}
            disabled={disabled}
            className="text-sm text-gray-400 hover:text-gray-600"
          >
            Cancel
          </button>
        </>
      ) : (
        <button
          onClick={startRecording}
          disabled={disabled}
          className="flex items-center gap-1 px-3 py-1.5 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 text-sm"
        >
          <Mic className="w-3.5 h-3.5" />
          Record
        </button>
      )}
    </div>
  );
}
