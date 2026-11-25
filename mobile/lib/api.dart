import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

typedef Json = Map<String, dynamic>;

class ApiFailure implements Exception {
  final String message;
  const ApiFailure(this.message);
  @override
  String toString() => message;
}

class LiveGreenApi {
  static const defaultBase = String.fromEnvironment(
    'API_BASE',
    defaultValue: 'https://greenwithisd.pythonanywhere.com',
  );
  final FlutterSecureStorage storage;
  final http.Client client;
  LiveGreenApi({http.Client? client, FlutterSecureStorage? storage})
    : client = client ?? http.Client(),
      storage = storage ?? const FlutterSecureStorage();
  String base = defaultBase;
  String? token;
  Json? account;
  bool get connected => token != null;

  static String validateBase(String value) {
    final uri = Uri.tryParse(value.trim());
    final local =
        uri != null &&
        kDebugMode &&
        ['localhost', '127.0.0.1', '10.0.2.2'].contains(uri.host) &&
        uri.scheme == 'http';
    if (uri == null ||
        uri.host.isEmpty ||
        (uri.scheme != 'https' && !local) ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        (uri.path != '' && uri.path != '/')) {
      throw const ApiFailure('Use an HTTPS server address without a path.');
    }
    return uri.replace(path: '').toString();
  }

  Future<void> restore() async {
    final saved = await storage.read(key: 'connection');
    if (saved == null) return;
    final data = jsonDecode(saved) as Json;
    base = validateBase(data['base'] as String);
    token = data['token'] as String?;
  }

  Future<Json> request(String path, {String method = 'GET', Json? body}) async {
    try {
      final request = http.Request(method, Uri.parse('$base$path'))
        ..followRedirects = false
        ..headers['Accept'] = 'application/json';
      if (token != null) request.headers['Authorization'] = 'Bearer $token';
      if (body != null) {
        request.headers['Content-Type'] = 'application/json';
        request.body = jsonEncode(body);
      }
      final response = await client
          .send(request)
          .timeout(const Duration(seconds: 20));
      final text = await response.stream.bytesToString().timeout(
        const Duration(seconds: 20),
      );
      Json data;
      try {
        data = jsonDecode(text) as Json;
      } catch (_) {
        throw const ApiFailure(
          'This server does not provide the activity API yet. Check the server address or deploy the updated backend.',
        );
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        if (response.statusCode == 401) {
          throw const ApiFailure(
            'Account key not accepted. Check your connection in You.',
          );
        }
        if (response.statusCode == 409) {
          throw const ApiFailure(
            'This record changed elsewhere. Close it and refresh before editing again.',
          );
        }
        throw ApiFailure(
          data['message'] as String? ??
              'Request failed (${response.statusCode}).',
        );
      }
      return data;
    } on TimeoutException {
      throw const ApiFailure(
        'Server timed out. Your changes have not been confirmed; retry when connected.',
      );
    } on SocketException {
      throw const ApiFailure('Cannot reach the server. Check your connection.');
    } on http.ClientException {
      throw const ApiFailure(
        'Cannot reach the server. For USB preview, keep the cable connected.',
      );
    }
  }

  Future<void> connect(String server, String key) async {
    final nextBase = validateBase(server);
    final nextToken = key.trim();
    if (nextToken.length < 24 ||
        nextToken.length > 200 ||
        !RegExp(r'^[\x21-\x7e]+$').hasMatch(nextToken)) {
      throw const ApiFailure('Enter your account-specific activity key.');
    }
    final oldBase = base, oldToken = token;
    final oldAccount = account;
    base = nextBase;
    token = nextToken;
    try {
      account = (await request('/api/v1/activity-account'))['account'] as Json;
      await storage.write(
        key: 'connection',
        value: jsonEncode({'base': base, 'token': token}),
      );
    } catch (_) {
      base = oldBase;
      token = oldToken;
      account = oldAccount;
      rethrow;
    }
  }

  Future<void> disconnect() async {
    await storage.delete(key: 'connection');
    token = null;
    account = null;
    base = defaultBase;
  }

  String endpoint(String suffix) =>
      connected ? '/api/v1/activity-$suffix' : '/api/v1/demo/$suffix';
  Future<Json> overview(String start, String end) =>
      request('${endpoint('overview')}?start=$start&end=$end');
  Future<List<Json>> events(String start, String end) async =>
      ((await request(
                '${endpoint('events')}?start=$start&end=$end${connected ? '&include_undated=1' : ''}',
              ))['items']
              as List)
          .cast<Json>();
  Future<List<Json>> factors() async =>
      ((await request('/api/v1/activity-factors'))['items'] as List)
          .cast<Json>();
  Future<Json> save(Json payload, {Json? original}) async {
    final data = {...payload};
    var path = '/api/v1/activity-events';
    var method = 'POST';
    if (original != null) {
      path += '/${Uri.encodeComponent(original['id'] as String)}';
      method = 'PATCH';
      data['expected_revision'] = original['revision'];
    }
    return (await request(path, method: method, body: data))['event'] as Json;
  }

  void close() => client.close();
}
