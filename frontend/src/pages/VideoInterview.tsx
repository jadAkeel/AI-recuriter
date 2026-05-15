import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { Video, VideoOff, Mic, MicOff, Phone, PhoneOff, Loader, AlertCircle, User } from 'lucide-react';
import { useWebRTC } from '../hooks/useWebRTC';
import { buildApiWebSocketUrl } from '../utils/network';

export default function VideoInterview() {
  const { session_id } = useParams<{ session_id: string }>();
  const localVideoRef = useRef<HTMLVideoElement>(null);
  const remoteVideoRef = useRef<HTMLVideoElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [audioMuted, setAudioMuted] = useState(false);
  const [videoMuted, setVideoMuted] = useState(false);
  const [error, setError] = useState('');

  const {
    localStream,
    remoteStream,
    isConnected,
    isCalling,
    error: rtcError,
    startLocalStream,
    stopLocalStream,
    createOffer,
    handleSignalingMessage,
  } = useWebRTC(wsRef, session_id || '');

  useEffect(() => {
    if (!session_id) return;

    const ws = new WebSocket(buildApiWebSocketUrl(`/ws/interview/${session_id}`));
    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
    };

    ws.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'webrtc_offer' || msg.type === 'webrtc_answer' || msg.type === 'webrtc_ice') {
          await handleSignalingMessage(msg);
        }
      } catch {
        // ignore non-JSON messages
      }
    };

    ws.onerror = () => setError('WebSocket connection failed');

    ws.onclose = () => {
      setWsConnected(false);
      wsRef.current = null;
    };

    return () => {
      ws.close();
      stopLocalStream();
    };
  }, [session_id, handleSignalingMessage, stopLocalStream]);

  useEffect(() => {
    if (localVideoRef.current && localStream) {
      localVideoRef.current.srcObject = localStream;
    }
  }, [localStream]);

  useEffect(() => {
    if (remoteVideoRef.current && remoteStream) {
      remoteVideoRef.current.srcObject = remoteStream;
    }
  }, [remoteStream]);

  const toggleAudio = useCallback(() => {
    if (localStream) {
      localStream.getAudioTracks().forEach((t) => { t.enabled = audioMuted; });
      setAudioMuted(!audioMuted);
    }
  }, [localStream, audioMuted]);

  const toggleVideo = useCallback(() => {
    if (localStream) {
      localStream.getVideoTracks().forEach((t) => { t.enabled = videoMuted; });
      setVideoMuted(!videoMuted);
    }
  }, [localStream, videoMuted]);

  const startCall = useCallback(async () => {
    try {
      await startLocalStream();
      await createOffer();
    } catch {
      setError('Could not start video call');
    }
  }, [startLocalStream, createOffer]);

  const endCall = useCallback(() => {
    stopLocalStream();
    wsRef.current?.close();
  }, [stopLocalStream]);

  if (error || rtcError) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-900 p-4">
        <div className="bg-gray-800 rounded-xl p-8 text-center max-w-md">
          <AlertCircle className="w-12 h-12 text-red-400 mx-auto mb-4" />
          <p className="text-gray-300">{error || rtcError}</p>
          <button onClick={() => window.location.reload()} className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600">
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 flex flex-col">
      <div className="flex-1 flex items-center justify-center p-4 relative">
        {remoteStream ? (
          <video ref={remoteVideoRef} autoPlay playsInline className="w-full h-full object-contain rounded-xl bg-gray-800" />
        ) : (
          <div className="flex flex-col items-center text-gray-400">
            <User className="w-24 h-24 mb-4" />
            <p className="text-lg">AI Interviewer</p>
            {!wsConnected && (
              <div className="flex items-center gap-2 mt-2 text-sm">
                <Loader className="w-4 h-4 animate-spin" />
                Connecting...
              </div>
            )}
          </div>
        )}

        <div className="absolute bottom-4 right-4 w-48 h-36 rounded-lg overflow-hidden border-2 border-gray-600 bg-gray-800">
          {localStream ? (
            <video ref={localVideoRef} autoPlay playsInline muted className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-gray-500 text-sm">
              Camera off
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center justify-center gap-4 p-4 bg-gray-800">
        <button
          onClick={toggleAudio}
          className={`p-3 rounded-full ${audioMuted ? 'bg-red-500' : 'bg-gray-600'} text-white hover:opacity-80`}
        >
          {audioMuted ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
        </button>

        {isConnected ? (
          <button onClick={endCall} className="p-3 rounded-full bg-red-500 text-white hover:bg-red-600">
            <PhoneOff className="w-5 h-5" />
          </button>
        ) : (
          <button
            onClick={startCall}
            disabled={!wsConnected || isCalling}
            className="p-3 rounded-full bg-green-500 text-white hover:bg-green-600 disabled:opacity-50"
          >
            {isCalling ? <Loader className="w-5 h-5 animate-spin" /> : <Phone className="w-5 h-5" />}
          </button>
        )}

        <button
          onClick={toggleVideo}
          className={`p-3 rounded-full ${videoMuted ? 'bg-red-500' : 'bg-gray-600'} text-white hover:opacity-80`}
        >
          {videoMuted ? <VideoOff className="w-5 h-5" /> : <Video className="w-5 h-5" />}
        </button>
      </div>

      {!wsConnected && (
        <div className="absolute top-4 left-4 flex items-center gap-2 bg-yellow-500/20 text-yellow-300 px-3 py-1 rounded text-sm">
          <Loader className="w-3.5 h-3.5 animate-spin" />
          Connecting to server...
        </div>
      )}
    </div>
  );
}
