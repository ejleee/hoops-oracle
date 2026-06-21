import { useEffect, useRef, useState } from 'react';
import { io } from 'socket.io-client';

const SOCKET_URL = 'http://localhost:5001';

/**
 * Connects to /live and returns:
 *   gameUpdates  – map of game_id → latest state (all live games)
 *   gamesList    – summary array for the selector UI
 *   connected    – WebSocket status
 */
export default function useGameSocket() {
  const socketRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const [gameUpdates, setGameUpdates] = useState({});  // { [game_id]: state }
  const [gamesList, setGamesList] = useState([]);

  useEffect(() => {
    const socket = io(SOCKET_URL + '/live');
    socketRef.current = socket;

    socket.on('connect', () => setConnected(true));
    socket.on('disconnect', () => setConnected(false));

    socket.on('game_update', (data) => {
      console.log('[game_update]', data.home_win_prob, 'seconds_remaining:', data.seconds_remaining, 'score_diff:', data.score_differential);
      setGameUpdates(prev => ({ ...prev, [data.game_id]: data }));
    });

    socket.on('games_list', (list) => {
      setGamesList(list);
    });

    return () => socket.disconnect();
  }, []);

  return { gameUpdates, gamesList, connected };
}
