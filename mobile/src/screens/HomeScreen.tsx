import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl, Alert, Modal, TextInput,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { api } from '../services/api';
import { useAuth } from '../context/AuthContext';
import type { Room } from '../types';

const STATUS_CONFIG = {
  available: { label: 'AVAILABLE', color: '#34d399', bg: 'rgba(16,185,129,0.15)', borderColor: 'rgba(16,185,129,0.30)', cardBorder: 'rgba(16,185,129,0.25)' },
  occupied:  { label: 'OCCUPIED',  color: '#f87171', bg: 'rgba(239,68,68,0.15)',  borderColor: 'rgba(239,68,68,0.30)',  cardBorder: 'rgba(239,68,68,0.25)'  },
  booked:    { label: 'BOOKED',    color: '#fbbf24', bg: 'rgba(234,179,8,0.15)',  borderColor: 'rgba(234,179,8,0.30)',  cardBorder: 'rgba(234,179,8,0.25)'  },
};

export default function HomeScreen() {
  const { user } = useAuth();
  const [rooms, setRooms]           = useState<Room[]>([]);
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState('');

  // Admin override modal state
  const [overrideModal, setOverrideModal]   = useState(false);
  const [overrideRoom, setOverrideRoom]     = useState<Room | null>(null);
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideLoading, setOverrideLoading] = useState(false);

  const load = useCallback(async (isRefresh = false) => {
    try {
      if (!isRefresh) setLoading(true);
      const data = await api.getRooms();
      setRooms(data);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e: any) {
      Alert.alert('Error', e.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = () => { setRefreshing(true); load(true); };

  const openOverrideModal = (room: Room) => {
    setOverrideRoom(room);
    setOverrideReason('');
    setOverrideModal(true);
  };

  const handleSetOverride = async () => {
    if (!overrideRoom) return;
    setOverrideLoading(true);
    try {
      await api.setRoomOverride(overrideRoom.id, overrideReason.trim() || 'Maintenance');
      setOverrideModal(false);
      load(true);
    } catch (e: any) {
      Alert.alert('Error', e.message);
    } finally {
      setOverrideLoading(false);
    }
  };

  const handleClearOverride = (room: Room) => {
    Alert.alert(
      'Clear Override',
      `Remove the "${room.override_reason}" override for ${room.name}?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Clear',
          style: 'destructive',
          onPress: async () => {
            try {
              await api.clearRoomOverride(room.id);
              load(true);
            } catch (e: any) {
              Alert.alert('Error', e.message);
            }
          },
        },
      ],
    );
  };

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator size="large" color="#00AFEF" />
      </View>
    );
  }

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView
        style={s.root}
        contentContainerStyle={s.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#00AFEF" />}
        showsVerticalScrollIndicator={false}
      >
        {/* Header */}
        <View style={s.header}>
          <View>
            <Text style={s.greeting}>Good {getGreeting()},</Text>
            <Text style={s.name}>{user?.name?.split(' ')[0]}</Text>
          </View>
          <TouchableOpacity style={s.refreshBtn} onPress={onRefresh}>
            <Ionicons name="refresh-outline" size={20} color="#00AFEF" />
          </TouchableOpacity>
        </View>

        {/* Section label */}
        <Text style={s.sectionLabel}>LIVE ROOM STATUS</Text>
        {lastUpdated ? <Text style={s.updatedAt}>Updated at {lastUpdated}</Text> : null}

        {/* Cards */}
        <View style={s.grid}>
          {rooms.map((room) => (
            <RoomCard
              key={room.id}
              room={room}
              isAdmin={user?.is_admin ?? false}
              onSetOverride={() => openOverrideModal(room)}
              onClearOverride={() => handleClearOverride(room)}
            />
          ))}
        </View>
      </ScrollView>

      {/* Admin override modal */}
      <Modal visible={overrideModal} transparent animationType="slide" onRequestClose={() => setOverrideModal(false)}>
        <TouchableOpacity style={m.backdrop} activeOpacity={1} onPress={() => setOverrideModal(false)}>
          <View style={m.sheet}>
            <View style={m.handle} />
            <Text style={m.title}>Mark Room as Occupied</Text>
            {overrideRoom && (
              <Text style={m.roomName}>{overrideRoom.name}</Text>
            )}
            <Text style={m.label}>Reason</Text>
            <TextInput
              style={m.input}
              placeholder="e.g. Maintenance, Cleaning, VIP event..."
              placeholderTextColor="#3a5070"
              value={overrideReason}
              onChangeText={setOverrideReason}
              autoFocus
            />
            <TouchableOpacity
              style={[m.confirmBtn, overrideLoading && m.disabled]}
              onPress={handleSetOverride}
              disabled={overrideLoading}
            >
              {overrideLoading
                ? <ActivityIndicator color="#fff" />
                : <Text style={m.confirmText}>Mark as Occupied</Text>
              }
            </TouchableOpacity>
            <TouchableOpacity style={m.cancelBtn} onPress={() => setOverrideModal(false)}>
              <Text style={m.cancelText}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

function RoomCard({ room, isAdmin, onSetOverride, onClearOverride }: {
  room: Room;
  isAdmin: boolean;
  onSetOverride: () => void;
  onClearOverride: () => void;
}) {
  const cfg = STATUS_CONFIG[room.status];

  // Override styling — purple tint
  const cardBorder = room.has_override ? 'rgba(168,85,247,0.35)' : cfg.cardBorder;
  const pillBg     = room.has_override ? 'rgba(168,85,247,0.15)' : cfg.bg;
  const pillBorder = room.has_override ? 'rgba(168,85,247,0.35)' : cfg.borderColor;
  const pillColor  = room.has_override ? '#c084fc' : cfg.color;
  const pillLabel  = room.has_override ? 'OVERRIDE' : cfg.label;

  return (
    <View style={[s.card, { borderColor: cardBorder }]}>
      <View style={s.cardHeader}>
        <Text style={s.floor}>Floor {room.floor}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <View style={[s.pill, { backgroundColor: pillBg, borderColor: pillBorder }]}>
            <View style={[s.dot, { backgroundColor: pillColor }]} />
            <Text style={[s.pillText, { color: pillColor }]}>{pillLabel}</Text>
          </View>
          {/* Admin wrench button */}
          {isAdmin && (
            <TouchableOpacity
              style={s.adminBtn}
              onPress={room.has_override ? onClearOverride : onSetOverride}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            >
              <Ionicons
                name={room.has_override ? 'lock-open-outline' : 'build-outline'}
                size={16}
                color={room.has_override ? '#c084fc' : '#8fa8c8'}
              />
            </TouchableOpacity>
          )}
        </View>
      </View>

      <Text style={s.roomSize}>{room.size}</Text>
      <Text style={s.amenities}>{room.amenities.join(' · ')}</Text>

      {room.has_override && room.override_reason && (
        <View style={s.overrideInfo}>
          <Text style={s.overrideText}>{room.override_reason}</Text>
        </View>
      )}

      {!room.has_override && room.status === 'occupied' && room.booking && (
        <View style={s.bookingInfo}>
          <Text style={s.bookingUntil}>Until {room.booking.end_time}</Text>
          <Text style={s.bookingBy}>{room.booking.booked_by}</Text>
        </View>
      )}
      {!room.has_override && room.status === 'booked' && room.booking && (
        <View style={s.bookingInfo}>
          <Text style={s.bookingFrom}>From {room.booking.start_time}</Text>
        </View>
      )}
    </View>
  );
}

function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return 'morning';
  if (h < 17) return 'afternoon';
  return 'evening';
}

const s = StyleSheet.create({
  safe:    { flex: 1, backgroundColor: '#040e1f' },
  root:    { flex: 1, backgroundColor: '#040e1f' },
  content: { padding: 20, paddingBottom: 40 },
  center:  { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#040e1f' },

  header:  { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 },
  greeting:{ color: '#8fa8c8', fontSize: 14 },
  name:    { color: '#f7f4ed', fontSize: 22, fontWeight: '700' },
  refreshBtn: {
    backgroundColor: 'rgba(0,175,239,0.12)', borderRadius: 10,
    width: 38, height: 38, alignItems: 'center', justifyContent: 'center',
  },

  sectionLabel: { color: '#00AFEF', fontSize: 11, fontWeight: '700', letterSpacing: 1.3, marginBottom: 4 },
  updatedAt:    { color: '#4a6080', fontSize: 11, marginBottom: 16 },

  grid: { gap: 12 },
  card: {
    backgroundColor: 'rgba(4,20,48,0.8)', borderRadius: 18, borderWidth: 1,
    padding: 16, shadowColor: '#000', shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.2, shadowRadius: 8, elevation: 4,
  },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  floor:      { color: '#f1f5f9', fontSize: 18, fontWeight: '700' },
  pill: {
    flexDirection: 'row', alignItems: 'center', gap: 5,
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, borderWidth: 1,
  },
  dot:      { width: 6, height: 6, borderRadius: 3 },
  pillText: { fontSize: 10, fontWeight: '700', letterSpacing: 0.8 },
  adminBtn: {
    backgroundColor: 'rgba(255,255,255,0.06)', borderRadius: 8,
    width: 30, height: 30, alignItems: 'center', justifyContent: 'center',
  },
  roomSize:  { color: '#94a3b8', fontSize: 13, marginBottom: 2 },
  amenities: { color: '#64748b', fontSize: 12 },
  overrideInfo: { marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: 'rgba(168,85,247,0.15)' },
  overrideText: { color: '#c084fc', fontSize: 13, fontWeight: '600' },
  bookingInfo: { marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.06)' },
  bookingUntil:{ color: '#f87171', fontSize: 13, fontWeight: '600' },
  bookingFrom: { color: '#fbbf24', fontSize: 13, fontWeight: '600' },
  bookingBy:   { color: '#94a3b8', fontSize: 12, marginTop: 2 },
});

const m = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: '#071629', borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: 24, paddingBottom: 40,
  },
  handle: {
    width: 40, height: 4, backgroundColor: 'rgba(255,255,255,0.2)',
    borderRadius: 2, alignSelf: 'center', marginBottom: 20,
  },
  title:    { color: '#f7f4ed', fontSize: 18, fontWeight: '700', marginBottom: 4 },
  roomName: { color: '#8fa8c8', fontSize: 13, marginBottom: 20 },
  label:    { color: '#8fa8c8', fontSize: 13, fontWeight: '600', marginBottom: 6 },
  input: {
    backgroundColor: 'rgba(255,255,255,0.05)', borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)', borderRadius: 12,
    color: '#f7f4ed', fontSize: 15,
    paddingHorizontal: 14, paddingVertical: 13, marginBottom: 16,
  },
  confirmBtn: {
    backgroundColor: '#a855f7', borderRadius: 14,
    paddingVertical: 14, alignItems: 'center', marginBottom: 10,
  },
  confirmText: { color: '#fff', fontSize: 15, fontWeight: '700' },
  cancelBtn: {
    backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: 14,
    paddingVertical: 14, alignItems: 'center',
  },
  cancelText: { color: '#8fa8c8', fontSize: 15, fontWeight: '600' },
  disabled: { opacity: 0.6 },
});
