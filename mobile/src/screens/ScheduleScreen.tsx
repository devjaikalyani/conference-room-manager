import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator,
  RefreshControl, Alert, TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';
import { api } from '../services/api';
import { useAuth } from '../context/AuthContext';
import type { RoomSchedule } from '../types';

export default function ScheduleScreen() {
  const { user } = useAuth();
  const [schedule, setSchedule]   = useState<RoomSchedule[]>([]);
  const [loading, setLoading]     = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (isRefresh = false) => {
    try {
      if (!isRefresh) setLoading(true);
      const data = await api.getTodaySchedule();
      setSchedule(data);
    } catch (e: any) {
      Alert.alert('Error', e.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const today = new Date().toLocaleDateString('en-IN', {
    weekday: 'long', day: 'numeric', month: 'long',
  });

  const handleCancel = (id: number, bookedBy: string) => {
    if (!user?.is_admin && bookedBy.toLowerCase() !== user?.name.toLowerCase()) {
      return Alert.alert('Not Allowed', 'You can only cancel your own bookings.');
    }
    Alert.alert('Cancel Booking', 'Are you sure you want to cancel this booking?', [
      { text: 'No', style: 'cancel' },
      {
        text: 'Yes, Cancel', style: 'destructive',
        onPress: async () => {
          try {
            await api.cancelBooking(id);
            load(true);
          } catch (e: any) {
            Alert.alert('Error', e.message);
          }
        },
      },
    ]);
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
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(true); }} tintColor="#00AFEF" />}
        showsVerticalScrollIndicator={false}
      >
        <Text style={s.title}>Today's Schedule</Text>
        <Text style={s.dateText}>{today}</Text>

        {schedule.map((room) => (
          <View key={room.room_id} style={s.section}>
            <View style={s.roomHeader}>
              <Ionicons name="business-outline" size={16} color="#00AFEF" />
              <Text style={s.roomName}>{room.room_name}</Text>
            </View>

            {room.bookings.length === 0 ? (
              <View style={s.emptyBox}>
                <Text style={s.emptyText}>No bookings today</Text>
              </View>
            ) : (
              room.bookings.map((b) => (
                <View key={b.id} style={[s.bookingCard, b.is_now && s.bookingNow]}>
                  <View style={s.bookingLeft}>
                    <View style={s.bookingTimeRow}>
                      <Text style={[s.bookingTime, b.is_now && s.bookingTimeNow]}>
                        {b.start_time} – {b.end_time}
                      </Text>
                      {b.is_now && (
                        <View style={s.nowBadge}>
                          <Text style={s.nowText}>NOW</Text>
                        </View>
                      )}
                    </View>
                    <Text style={s.bookingWho}>{b.booked_by}</Text>
                    {b.purpose ? <Text style={s.bookingPurpose}>{b.purpose}</Text> : null}
                  </View>
                  {b.can_cancel && (
                    <TouchableOpacity
                      style={s.cancelBtn}
                      onPress={() => handleCancel(b.id, b.booked_by)}
                    >
                      <Ionicons name="trash-outline" size={16} color="#f87171" />
                    </TouchableOpacity>
                  )}
                </View>
              ))
            )}
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe:    { flex: 1, backgroundColor: '#040e1f' },
  root:    { flex: 1, backgroundColor: '#040e1f' },
  content: { padding: 20, paddingBottom: 48 },
  center:  { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#040e1f' },
  title:   { color: '#f7f4ed', fontSize: 24, fontWeight: '700', marginBottom: 2 },
  dateText:{ color: '#00AFEF', fontSize: 13, fontWeight: '600', marginBottom: 24 },

  section: { marginBottom: 20 },
  roomHeader: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 10,
  },
  roomName: { color: '#f7f4ed', fontSize: 15, fontWeight: '700' },

  emptyBox: {
    backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: 12,
    paddingVertical: 14, alignItems: 'center',
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)',
  },
  emptyText: { color: '#4a6080', fontSize: 13 },

  bookingCard: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: 14, borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.07)',
    padding: 14, marginBottom: 8,
  },
  bookingNow: {
    backgroundColor: 'rgba(239,68,68,0.07)',
    borderColor: 'rgba(239,68,68,0.25)',
  },
  bookingLeft: { flex: 1 },
  bookingTimeRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4 },
  bookingTime:    { color: '#93c5fd', fontSize: 14, fontWeight: '600' },
  bookingTimeNow: { color: '#f87171' },
  nowBadge: {
    backgroundColor: 'rgba(239,68,68,0.25)', borderRadius: 999,
    paddingHorizontal: 7, paddingVertical: 2,
    borderWidth: 1, borderColor: 'rgba(239,68,68,0.4)',
  },
  nowText: { color: '#f87171', fontSize: 9, fontWeight: '700', letterSpacing: 0.8 },
  bookingWho:     { color: '#e2e8f0', fontSize: 13 },
  bookingPurpose: { color: '#94a3b8', fontSize: 12, marginTop: 2 },
  cancelBtn: {
    backgroundColor: 'rgba(239,68,68,0.1)', borderRadius: 8,
    width: 34, height: 34, alignItems: 'center', justifyContent: 'center',
  },
});
