import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, Modal, FlatList, ActivityIndicator, Alert, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import DateTimePicker from '@react-native-community/datetimepicker';
import { api } from '../services/api';
import { useAuth } from '../context/AuthContext';

const ROOMS = [
  { id: 5, label: 'Floor 5 – Large' },
  { id: 4, label: 'Floor 4 – Large' },
  { id: 3, label: 'Floor 3 – Small' },
  { id: 2, label: 'Floor 2 – Small' },
];

export default function BookRoomScreen() {
  const { user } = useAuth();
  const [timeSlots, setTimeSlots] = useState<string[]>([]);
  const [selectedRoom, setSelectedRoom] = useState(ROOMS[0]);
  const [date, setDate]                 = useState(new Date());
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [startTime, setStartTime]       = useState('');
  const [endTime, setEndTime]           = useState('');
  const [purpose, setPurpose]           = useState('');
  const [roomModal, setRoomModal]       = useState(false);
  const [startModal, setStartModal]     = useState(false);
  const [endModal, setEndModal]         = useState(false);
  const [loading, setLoading]           = useState(false);
  const [checking, setChecking]         = useState(false);
  const [availMsg, setAvailMsg]         = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api.getTimeSlots().then((d) => {
      setTimeSlots(d.slots);
      setStartTime(d.slots[2]);
      setEndTime(d.slots[3]);
    });
  }, []);

  const startOptions = timeSlots.slice(0, -1);
  const endOptions   = timeSlots.slice(timeSlots.indexOf(startTime) + 1);
  const dateStr      = date.toISOString().split('T')[0];

  const handleCheckAvailability = async () => {
    if (!startTime || !endTime) return;
    setChecking(true);
    setAvailMsg(null);
    try {
      const result = await api.checkAvailability({
        room_id: selectedRoom.id,
        date: dateStr,
        start_time: startTime,
        end_time: endTime,
      });
      if (result.available) {
        setAvailMsg({ ok: true, text: `Room is available for ${startTime} – ${endTime}` });
      } else {
        const first = result.conflicts[0];
        const detail = first
          ? `\nConflict: ${first.start_time}${first.end_time ? ` – ${first.end_time}` : ''} · ${first.booked_by}`
          : '';
        setAvailMsg({ ok: false, text: `Room is not available for this slot.${detail}` });
      }
    } catch (e: any) {
      setAvailMsg({ ok: false, text: e.message });
    } finally {
      setChecking(false);
    }
  };

  const handleBook = async () => {
    if (!startTime || !endTime) return Alert.alert('Required', 'Please select start and end times.');
    setLoading(true);
    setAvailMsg(null);
    try {
      const booking = await api.createBooking({
        room_id: selectedRoom.id,
        date: dateStr,
        start_time: startTime,
        end_time: endTime,
        purpose: purpose.trim(),
      });
      Alert.alert(
        'Booked!',
        `${booking.room_name} booked for ${startTime} – ${endTime} on ${dateStr}`,
        [{ text: 'OK', onPress: () => { setPurpose(''); setAvailMsg(null); } }],
      );
    } catch (e: any) {
      Alert.alert('Booking Failed', e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView style={s.root} contentContainerStyle={s.content} showsVerticalScrollIndicator={false}>
        <Text style={s.title}>Book a Room</Text>
        <Text style={s.sub}>Select a conference room and time slot.</Text>

        {/* Room selector */}
        <Text style={s.label}>Conference Room</Text>
        <TouchableOpacity style={s.selector} onPress={() => setRoomModal(true)}>
          <Text style={s.selectorText}>{selectedRoom.label}</Text>
          <Ionicons name="chevron-down" size={18} color="#8fa8c8" />
        </TouchableOpacity>

        {/* Date picker */}
        <Text style={s.label}>Date</Text>
        <TouchableOpacity style={s.selector} onPress={() => setShowDatePicker(true)}>
          <Text style={s.selectorText}>{dateStr}</Text>
          <Ionicons name="calendar-outline" size={18} color="#8fa8c8" />
        </TouchableOpacity>

        {showDatePicker && (
          <DateTimePicker
            value={date}
            mode="date"
            minimumDate={new Date()}
            display={Platform.OS === 'ios' ? 'spinner' : 'default'}
            themeVariant="dark"
            onChange={(_, d) => { setShowDatePicker(false); if (d) setDate(d); }}
          />
        )}

        {/* Time row */}
        <View style={s.timeRow}>
          <View style={s.timeCol}>
            <Text style={s.label}>Start Time</Text>
            <TouchableOpacity style={s.selector} onPress={() => setStartModal(true)}>
              <Text style={s.selectorText}>{startTime || 'Select'}</Text>
              <Ionicons name="chevron-down" size={16} color="#8fa8c8" />
            </TouchableOpacity>
          </View>
          <View style={s.timeCol}>
            <Text style={s.label}>End Time</Text>
            <TouchableOpacity style={s.selector} onPress={() => setEndModal(true)}>
              <Text style={s.selectorText}>{endTime || 'Select'}</Text>
              <Ionicons name="chevron-down" size={16} color="#8fa8c8" />
            </TouchableOpacity>
          </View>
        </View>

        {/* Purpose */}
        <Text style={s.label}>Meeting Purpose <Text style={s.optional}>(optional)</Text></Text>
        <TextInput
          style={[s.input, { height: 64, textAlignVertical: 'top' }]}
          placeholder="e.g. Team standup, Client call..."
          placeholderTextColor="#3a5070"
          value={purpose}
          onChangeText={setPurpose}
          multiline
        />

        {/* Booked by (read-only) */}
        <Text style={s.label}>Booked By</Text>
        <View style={[s.selector, { opacity: 0.6 }]}>
          <Text style={s.selectorText}>{user?.name}</Text>
          <Ionicons name="lock-closed-outline" size={16} color="#8fa8c8" />
        </View>

        {/* Availability message */}
        {availMsg && (
          <View style={[s.msgBox, { borderColor: availMsg.ok ? 'rgba(52,211,153,0.4)' : 'rgba(248,113,113,0.4)' }]}>
            <Ionicons
              name={availMsg.ok ? 'checkmark-circle-outline' : 'close-circle-outline'}
              size={18} color={availMsg.ok ? '#34d399' : '#f87171'}
            />
            <Text style={[s.msgText, { color: availMsg.ok ? '#34d399' : '#f87171' }]}>
              {availMsg.text}
            </Text>
          </View>
        )}

        {/* Buttons */}
        <TouchableOpacity style={s.checkBtn} onPress={handleCheckAvailability} disabled={checking}>
          {checking
            ? <ActivityIndicator color="#00AFEF" size="small" />
            : <><Ionicons name="search-outline" size={16} color="#00AFEF" />
               <Text style={s.checkBtnText}>Check Availability</Text></>
          }
        </TouchableOpacity>

        <TouchableOpacity style={[s.bookBtn, loading && s.disabled]} onPress={handleBook} disabled={loading}>
          {loading
            ? <ActivityIndicator color="#fff" />
            : <Text style={s.bookBtnText}>Book Room</Text>
          }
        </TouchableOpacity>
      </ScrollView>

      {/* Room Modal */}
      <PickerModal
        visible={roomModal}
        onClose={() => setRoomModal(false)}
        title="Select Room"
        items={ROOMS.map((r) => ({ label: r.label, value: r.id }))}
        selectedValue={selectedRoom.id}
        onSelect={(id) => { setSelectedRoom(ROOMS.find((r) => r.id === id)!); setRoomModal(false); }}
      />

      {/* Start time Modal */}
      <PickerModal
        visible={startModal}
        onClose={() => setStartModal(false)}
        title="Start Time"
        items={startOptions.map((t) => ({ label: t, value: t }))}
        selectedValue={startTime}
        onSelect={(t) => {
          setStartTime(t as string);
          const newEnd = timeSlots[timeSlots.indexOf(t as string) + 1];
          setEndTime(newEnd || '');
          setStartModal(false);
        }}
      />

      {/* End time Modal */}
      <PickerModal
        visible={endModal}
        onClose={() => setEndModal(false)}
        title="End Time"
        items={endOptions.map((t) => ({ label: t, value: t }))}
        selectedValue={endTime}
        onSelect={(t) => { setEndTime(t as string); setEndModal(false); }}
      />
    </SafeAreaView>
  );
}

function PickerModal({ visible, onClose, title, items, selectedValue, onSelect }: {
  visible: boolean; onClose: () => void; title: string;
  items: { label: string; value: string | number }[];
  selectedValue: string | number;
  onSelect: (v: string | number) => void;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <TouchableOpacity style={pm.backdrop} activeOpacity={1} onPress={onClose}>
        <View style={pm.sheet}>
          <View style={pm.handle} />
          <Text style={pm.title}>{title}</Text>
          <FlatList
            data={items}
            keyExtractor={(i) => String(i.value)}
            renderItem={({ item }) => (
              <TouchableOpacity
                style={[pm.item, item.value === selectedValue && pm.itemActive]}
                onPress={() => onSelect(item.value)}
              >
                <Text style={[pm.itemText, item.value === selectedValue && pm.itemTextActive]}>
                  {item.label}
                </Text>
                {item.value === selectedValue && <Ionicons name="checkmark" size={18} color="#00AFEF" />}
              </TouchableOpacity>
            )}
          />
        </View>
      </TouchableOpacity>
    </Modal>
  );
}

const s = StyleSheet.create({
  safe:    { flex: 1, backgroundColor: '#040e1f' },
  root:    { flex: 1, backgroundColor: '#040e1f' },
  content: { padding: 20, paddingBottom: 48 },
  title:   { color: '#f7f4ed', fontSize: 24, fontWeight: '700', marginBottom: 4 },
  sub:     { color: '#8fa8c8', fontSize: 14, marginBottom: 24 },
  label:   { color: '#8fa8c8', fontSize: 13, fontWeight: '600', marginBottom: 6 },
  optional:{ color: '#4a6080', fontWeight: '400' },
  selector: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: 'rgba(255,255,255,0.05)', borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)', borderRadius: 12,
    paddingHorizontal: 14, paddingVertical: 13, marginBottom: 16,
  },
  selectorText: { color: '#f7f4ed', fontSize: 15 },
  timeRow: { flexDirection: 'row', gap: 12 },
  timeCol: { flex: 1 },
  input: {
    backgroundColor: 'rgba(255,255,255,0.05)', borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)', borderRadius: 12,
    color: '#f7f4ed', fontSize: 15,
    paddingHorizontal: 14, paddingVertical: 12, marginBottom: 16,
  },
  msgBox: {
    flexDirection: 'row', alignItems: 'flex-start', gap: 8,
    backgroundColor: 'rgba(255,255,255,0.03)',
    borderRadius: 10, borderWidth: 1, padding: 12, marginBottom: 14,
  },
  msgText: { fontSize: 13, flex: 1, lineHeight: 18 },
  checkBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
    backgroundColor: 'rgba(0,175,239,0.12)',
    borderWidth: 1, borderColor: 'rgba(0,175,239,0.3)',
    borderRadius: 14, paddingVertical: 13, marginBottom: 12,
  },
  checkBtnText: { color: '#00AFEF', fontSize: 15, fontWeight: '600' },
  bookBtn: {
    backgroundColor: '#00AFEF', borderRadius: 14,
    paddingVertical: 15, alignItems: 'center',
    shadowColor: '#00AFEF', shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.35, shadowRadius: 16, elevation: 6,
  },
  bookBtnText: { color: '#fff', fontSize: 16, fontWeight: '700' },
  disabled: { opacity: 0.6 },
});

const pm = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: '#071629', borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingBottom: 32, maxHeight: '70%',
  },
  handle: {
    width: 40, height: 4, backgroundColor: 'rgba(255,255,255,0.2)',
    borderRadius: 2, alignSelf: 'center', marginTop: 12, marginBottom: 16,
  },
  title: { color: '#f7f4ed', fontSize: 16, fontWeight: '700', paddingHorizontal: 20, marginBottom: 8 },
  item: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 20, paddingVertical: 14,
    borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.05)',
  },
  itemActive:     { backgroundColor: 'rgba(0,175,239,0.08)' },
  itemText:       { color: '#94a3b8', fontSize: 15 },
  itemTextActive: { color: '#00AFEF', fontWeight: '600' },
});
