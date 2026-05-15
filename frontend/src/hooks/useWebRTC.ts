import { useState, useRef, useCallback, useEffect } from 'react';

type WebRTCSignalMessage =
  | { type: 'webrtc_offer'; sdp: RTCSessionDescriptionInit }
  | { type: 'webrtc_answer'; sdp: RTCSessionDescriptionInit }
  | { type: 'webrtc_ice'; candidate: RTCIceCandidateInit };

const RTC_CONFIGURATION: RTCConfiguration = {
  iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
};

export interface UseWebRTCReturn {
  localStream: MediaStream | null;
  remoteStream: MediaStream | null;
  isConnected: boolean;
  isCalling: boolean;
  error: string | null;
  startLocalStream: () => Promise<MediaStream>;
  stopLocalStream: () => void;
  createOffer: () => Promise<void>;
  createAnswer: () => Promise<void>;
  handleSignalingMessage: (msg: WebRTCSignalMessage) => Promise<void>;
}

export function useWebRTC(wsRef: React.MutableRefObject<WebSocket | null>, sessionId: string): UseWebRTCReturn {
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isCalling, setIsCalling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const pendingCandidatesRef = useRef<RTCIceCandidateInit[]>([]);

  const startLocalStream = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      setLocalStream(stream);
      return stream;
    } catch (err) {
      const msg = err instanceof DOMException
        ? 'Camera/microphone access denied'
        : 'Failed to access media devices';
      setError(msg);
      throw err;
    }
  }, []);

  const stopLocalStream = useCallback(() => {
    localStream?.getTracks().forEach((t) => t.stop());
    setLocalStream(null);
    pcRef.current?.close();
    pcRef.current = null;
    setRemoteStream(null);
    setIsConnected(false);
    setIsCalling(false);
  }, [localStream]);

  const createPeerConnection = useCallback(async (stream: MediaStream) => {
    const pc = new RTCPeerConnection(RTC_CONFIGURATION);
    pcRef.current = pc;

    stream.getTracks().forEach((track) => {
      pc.addTrack(track, stream);
    });

    pc.ontrack = (event) => {
      setRemoteStream(event.streams[0] || null);
    };

    pc.onicecandidate = (event) => {
      if (event.candidate && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'webrtc_ice',
          target: sessionId,
          candidate: event.candidate.toJSON(),
        }));
      }
    };

    pc.oniceconnectionstatechange = () => {
      setIsConnected(pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed');
    };

    return pc;
  }, [sessionId, wsRef]);

  const createOffer = useCallback(async () => {
    setIsCalling(true);
    setError(null);

    try {
      const stream = localStream || await startLocalStream();
      const pc = await createPeerConnection(stream);

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      wsRef.current?.send(JSON.stringify({
        type: 'webrtc_offer',
        target: sessionId,
        sdp: pc.localDescription,
      }));
    } catch {
      setError('Failed to create offer');
      setIsCalling(false);
    }
  }, [localStream, startLocalStream, createPeerConnection, sessionId, wsRef]);

  const createAnswer = useCallback(async () => {
    setIsCalling(true);
    setError(null);

    try {
      const stream = localStream || await startLocalStream();
      const pc = await createPeerConnection(stream);

      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);

      wsRef.current?.send(JSON.stringify({
        type: 'webrtc_answer',
        target: sessionId,
        sdp: pc.localDescription,
      }));

      for (const candidate of pendingCandidatesRef.current) {
        await pc.addIceCandidate(new RTCIceCandidate(candidate));
      }
      pendingCandidatesRef.current = [];
    } catch {
      setError('Failed to create answer');
      setIsCalling(false);
    }
  }, [localStream, startLocalStream, createPeerConnection, sessionId, wsRef]);

  const handleSignalingMessage = useCallback(async (msg: WebRTCSignalMessage) => {
    const pc = pcRef.current;

    if (msg.type === 'webrtc_offer' && msg.sdp) {
      if (!pc) {
        const stream = localStream || await startLocalStream();
        const newPc = await createPeerConnection(stream);
        await newPc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
        const answer = await newPc.createAnswer();
        await newPc.setLocalDescription(answer);
        wsRef.current?.send(JSON.stringify({
          type: 'webrtc_answer',
          target: sessionId,
          sdp: newPc.localDescription,
        }));
        for (const c of pendingCandidatesRef.current) {
          await newPc.addIceCandidate(new RTCIceCandidate(c));
        }
        pendingCandidatesRef.current = [];
        return;
      }
      await pc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      wsRef.current?.send(JSON.stringify({
        type: 'webrtc_answer',
        target: sessionId,
        sdp: pc.localDescription,
      }));
    }

    if (msg.type === 'webrtc_answer' && msg.sdp && pc) {
      await pc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
      for (const c of pendingCandidatesRef.current) {
        await pc.addIceCandidate(new RTCIceCandidate(c));
      }
      pendingCandidatesRef.current = [];
    }

    if (msg.type === 'webrtc_ice' && msg.candidate) {
      if (pc?.remoteDescription) {
        await pc.addIceCandidate(new RTCIceCandidate(msg.candidate));
      } else {
        pendingCandidatesRef.current.push(msg.candidate);
      }
    }
  }, [localStream, startLocalStream, createPeerConnection, sessionId, wsRef]);

  useEffect(() => {
    return () => {
      stopLocalStream();
    };
  }, [stopLocalStream]);

  return {
    localStream,
    remoteStream,
    isConnected,
    isCalling,
    error,
    startLocalStream,
    stopLocalStream,
    createOffer,
    createAnswer,
    handleSignalingMessage,
  };
}
