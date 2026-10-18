/** Actual Python HTTP API + production TS delivery client; only notifier is fake. */
import test from 'node:test';
import { createElement } from '../../frontend/node_modules/react/index.js';
import { renderToStaticMarkup } from '../../frontend/node_modules/react-dom/server.node.js';
import { ObjectList } from '../../frontend/src/components/ObjectList.tsx';
import assert from 'node:assert/strict';
import { KeepsakeClient } from '../../integrations/photon/src/keepsake.ts';
import { ReminderDelivery } from '../../integrations/photon/src/reminders.ts';

const url = process.env.KEEPSAKE_QA_URL;
test('real HTTP memory -> query -> claim -> mocked send -> result, once', {skip: !url}, async () => {
  const origin = new URL(url!).origin;
  assert.equal(new URL(origin).hostname, '127.0.0.1');
  const localFetch: typeof fetch = async (input, init) => {
    assert.equal(new URL(String(input)).origin, origin, 'Network must stay in the isolated fixture');
    return fetch(input, init);
  };
  const client = new KeepsakeClient(origin, localFetch);
  const answer = await client.query('water bottle');
  assert.equal(answer.found, true);
  assert.match(answer.answer, /last saw/);
  assert.doesNotMatch(answer.answer, /side of|desk|couch/i);
  const memory = answer as typeof answer & { object: any };
  assert.equal("region" in memory.object, false);
  const card = renderToStaticMarkup(createElement(ObjectList, {
    objects: [memory.object], now: Date.now(), highlightId: null, onOpen: () => {},
  }));
  assert.match(card, /Water Bottle/);
  assert.match(card, /Last seen/);
  assert.doesNotMatch(card, /side of the room/);
  const queued = await client.queuedAlerts();
  assert.equal(queued.length, 1);
  const snap = queued[0]!.items[0]!.snapshot_id;
  const photo = await localFetch(`${origin}/api/snapshots/${snap}/image`);
  assert.equal(photo.status, 200);
  assert.equal(photo.headers.get('content-type'), 'image/jpeg');
  const sent: string[] = [];
  const notifier = {name:'FAKE-NO-NETWORK', send:async (_to:string, text:string) => { sent.push(text); }};
  const config = {projectId:'test-only',projectSecret:'test-only',keepsakeUrl:origin,
    alertsEnabled:true,recipients:['+15555550100'],pollMs:1000};
  const service = new ReminderDelivery(client, notifier, config, () => {}, 'UTC');
  const result = await service.poll();
  assert.equal(result.length, 1);
  assert.equal(result[0]!.accepted, 1);
  assert.equal(sent.length, 1);
  assert.match(sent[0]!, /water bottle/i);
  assert.doesNotMatch(sent[0]!, /forgot|side of|desk|couch/i);
  assert.deepEqual(await service.poll(), []);
  assert.equal(sent.length, 1);
});
