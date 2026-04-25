import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, Alert, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';

export default function ProfileScreen() {
  const { user, logout, refreshUser } = useAuth();
  const [changingPass, setChangingPass] = useState(false);
  const [oldPass, setOldPass]           = useState('');
  const [newPass, setNewPass]           = useState('');
  const [confirmPass, setConfirmPass]   = useState('');
  const [saving, setSaving]             = useState(false);
  const [showOld, setShowOld]           = useState(false);
  const [showNew, setShowNew]           = useState(false);

  const handleLogout = () => {
    Alert.alert('Sign Out', 'Are you sure you want to sign out?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Sign Out', style: 'destructive', onPress: logout },
    ]);
  };

  const handleChangePassword = async () => {
    if (!oldPass || !newPass || !confirmPass) {
      return Alert.alert('Required', 'Please fill in all password fields.');
    }
    if (newPass !== confirmPass) {
      return Alert.alert('Mismatch', 'New passwords do not match.');
    }
    if (newPass.length < 6) {
      return Alert.alert('Too Short', 'Password must be at least 6 characters.');
    }
    setSaving(true);
    try {
      await api.changePassword(oldPass, newPass);
      await refreshUser();
      Alert.alert('Success', 'Password changed successfully.');
      setChangingPass(false);
      setOldPass(''); setNewPass(''); setConfirmPass('');
    } catch (e: any) {
      Alert.alert('Error', e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView style={s.root} contentContainerStyle={s.content} showsVerticalScrollIndicator={false}>
        {/* Avatar + Name */}
        <View style={s.avatarSection}>
          <View style={s.avatar}>
            <Text style={s.avatarText}>
              {user?.name?.split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase()}
            </Text>
          </View>
          <Text style={s.name}>{user?.name}</Text>
          <View style={s.codeBadge}>
            <Text style={s.codeText}>{user?.employee_code}</Text>
          </View>
        </View>

        {/* Must change password banner */}
        {user?.must_change_password && (
          <TouchableOpacity style={s.warningBanner} onPress={() => setChangingPass(true)}>
            <Ionicons name="warning-outline" size={16} color="#fbbf24" />
            <Text style={s.warningText}>
              You are using your default password. Tap to set a new one.
            </Text>
          </TouchableOpacity>
        )}

        {/* Info cards */}
        <View style={s.infoCard}>
          {[
            { icon: 'business-outline', label: 'Branch', value: user?.branch },
            { icon: 'layers-outline',   label: 'Department', value: user?.department },
            { icon: 'briefcase-outline',label: 'Designation', value: user?.designation },
          ].map(({ icon, label, value }) => (
            <View key={label} style={s.infoRow}>
              <Ionicons name={icon as any} size={16} color="#00AFEF" />
              <View style={s.infoContent}>
                <Text style={s.infoLabel}>{label}</Text>
                <Text style={s.infoValue}>{value || '—'}</Text>
              </View>
            </View>
          ))}
        </View>

        {/* Change password section */}
        <TouchableOpacity style={s.actionBtn} onPress={() => setChangingPass(!changingPass)}>
          <Ionicons name="key-outline" size={18} color="#00AFEF" />
          <Text style={s.actionBtnText}>Change Password</Text>
          <Ionicons name={changingPass ? 'chevron-up' : 'chevron-down'} size={16} color="#8fa8c8" />
        </TouchableOpacity>

        {changingPass && (
          <View style={s.passForm}>
            <Text style={s.label}>Current Password</Text>
            <View style={s.passRow}>
              <TextInput
                style={[s.input, s.passInput]}
                placeholder="Enter current password"
                placeholderTextColor="#3a5070"
                value={oldPass}
                onChangeText={setOldPass}
                secureTextEntry={!showOld}
              />
              <TouchableOpacity style={s.eyeBtn} onPress={() => setShowOld(!showOld)}>
                <Ionicons name={showOld ? 'eye-off-outline' : 'eye-outline'} size={18} color="#8fa8c8" />
              </TouchableOpacity>
            </View>

            <Text style={s.label}>New Password</Text>
            <View style={s.passRow}>
              <TextInput
                style={[s.input, s.passInput]}
                placeholder="At least 6 characters"
                placeholderTextColor="#3a5070"
                value={newPass}
                onChangeText={setNewPass}
                secureTextEntry={!showNew}
              />
              <TouchableOpacity style={s.eyeBtn} onPress={() => setShowNew(!showNew)}>
                <Ionicons name={showNew ? 'eye-off-outline' : 'eye-outline'} size={18} color="#8fa8c8" />
              </TouchableOpacity>
            </View>

            <Text style={s.label}>Confirm New Password</Text>
            <TextInput
              style={s.input}
              placeholder="Re-enter new password"
              placeholderTextColor="#3a5070"
              value={confirmPass}
              onChangeText={setConfirmPass}
              secureTextEntry
            />

            <TouchableOpacity style={[s.saveBtn, saving && s.disabled]} onPress={handleChangePassword} disabled={saving}>
              {saving
                ? <ActivityIndicator color="#fff" />
                : <Text style={s.saveBtnText}>Save Password</Text>
              }
            </TouchableOpacity>
          </View>
        )}

        {/* Logout */}
        <TouchableOpacity style={s.logoutBtn} onPress={handleLogout}>
          <Ionicons name="log-out-outline" size={18} color="#f87171" />
          <Text style={s.logoutText}>Sign Out</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe:    { flex: 1, backgroundColor: '#040e1f' },
  root:    { flex: 1, backgroundColor: '#040e1f' },
  content: { padding: 20, paddingBottom: 48 },

  avatarSection: { alignItems: 'center', marginBottom: 24 },
  avatar: {
    width: 72, height: 72, borderRadius: 36,
    backgroundColor: '#00AFEF', alignItems: 'center', justifyContent: 'center',
    marginBottom: 12,
  },
  avatarText:   { color: '#fff', fontSize: 26, fontWeight: '800' },
  name:         { color: '#f7f4ed', fontSize: 20, fontWeight: '700', marginBottom: 8 },
  codeBadge: {
    backgroundColor: 'rgba(0,175,239,0.15)', borderRadius: 999,
    paddingHorizontal: 14, paddingVertical: 4,
    borderWidth: 1, borderColor: 'rgba(0,175,239,0.3)',
  },
  codeText: { color: '#00AFEF', fontSize: 13, fontWeight: '700' },

  warningBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    backgroundColor: 'rgba(234,179,8,0.1)',
    borderRadius: 12, borderWidth: 1,
    borderColor: 'rgba(234,179,8,0.3)',
    padding: 12, marginBottom: 20,
  },
  warningText: { color: '#fbbf24', fontSize: 13, flex: 1, lineHeight: 18 },

  infoCard: {
    backgroundColor: 'rgba(4,20,48,0.8)', borderRadius: 18,
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)',
    padding: 16, marginBottom: 16,
  },
  infoRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.05)' },
  infoContent: { flex: 1 },
  infoLabel:   { color: '#8fa8c8', fontSize: 11, fontWeight: '600', marginBottom: 2 },
  infoValue:   { color: '#f7f4ed', fontSize: 14 },

  actionBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    backgroundColor: 'rgba(0,175,239,0.08)',
    borderRadius: 14, borderWidth: 1,
    borderColor: 'rgba(0,175,239,0.2)',
    padding: 14, marginBottom: 0,
  },
  actionBtnText: { color: '#f7f4ed', fontSize: 15, fontWeight: '600', flex: 1 },

  passForm: {
    backgroundColor: 'rgba(4,20,48,0.8)', borderRadius: 14,
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)',
    padding: 16, marginTop: 8, marginBottom: 16,
  },
  label:    { color: '#8fa8c8', fontSize: 13, fontWeight: '600', marginBottom: 6 },
  input: {
    backgroundColor: 'rgba(255,255,255,0.05)', borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)', borderRadius: 12,
    color: '#f7f4ed', fontSize: 15,
    paddingHorizontal: 14, paddingVertical: 12, marginBottom: 14,
  },
  passRow:  { position: 'relative', marginBottom: 0 },
  passInput:{ marginBottom: 14, paddingRight: 48 },
  eyeBtn:   { position: 'absolute', right: 14, top: 12 },
  saveBtn: {
    backgroundColor: '#00AFEF', borderRadius: 12,
    paddingVertical: 12, alignItems: 'center', marginTop: 4,
  },
  saveBtnText: { color: '#fff', fontSize: 15, fontWeight: '700' },
  disabled:    { opacity: 0.6 },

  logoutBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
    backgroundColor: 'rgba(239,68,68,0.08)',
    borderRadius: 14, borderWidth: 1,
    borderColor: 'rgba(239,68,68,0.2)',
    paddingVertical: 14, marginTop: 16,
  },
  logoutText: { color: '#f87171', fontSize: 15, fontWeight: '600' },
});
