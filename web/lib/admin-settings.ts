import type { PublicSettings } from '@/lib/api';

export const DEFAULT_ADMIN_SETTINGS: PublicSettings = {
  siteName: 'MoYin.CC', tagline: '安静的声音栖地', registrationEnabled: true, passwordMinLength: 3,
  copy: { heroKicker: 'AUDIO ISLAND', heroTitle: 'MoYin.CC', heroSubtitle: '安静的声音栖地', primaryCta: '申请访问', secondaryCta: '进入账号中心', notice: '一处安静、专注的声音栖地。' },
  links: { libraryUrl: '', supportUrl: '', announcementUrl: '' },
  client: { serverUrl: 'https://listen.moyin.cc', androidDownloadUrl: 'https://mikupan.com/s/AOrU0', iosGuideText: '在 App Store 搜索“EchoShelf”并安装。', desktopGuideText: '暂无稳定方案，建议使用手机或平板。' },
  announcement: { title: '', body: '', linkUrl: '', linkLabel: '', timeline: [] },
  features: { registration: true, showLibraryEntry: false, showSupportEntry: false, showAnnouncements: true },
  operations: { inactivityAutoDisable: false, inactiveDays: 30, newUserGraceDays: 7, lastInactivityCheckAt: null, lastInactivityDisabled: 0 },
  sections: { benefits: [], steps: [], faq: [] },
};

export type AdminSettingsInput = Partial<Omit<PublicSettings,
  'copy' | 'links' | 'client' | 'announcement' | 'features' | 'operations' | 'sections'
>> & {
  copy?: Partial<PublicSettings['copy']>;
  links?: Partial<PublicSettings['links']>;
  client?: Partial<PublicSettings['client']>;
  announcement?: Partial<PublicSettings['announcement']>;
  features?: Partial<PublicSettings['features']>;
  operations?: Partial<PublicSettings['operations']>;
  sections?: Partial<PublicSettings['sections']>;
};

export type HydratedAdminSettings = {
  settings: PublicSettings;
  stepsText: string;
  faqText: string;
  timelineText: string;
};

export function hydrateAdminSettings(value: AdminSettingsInput = {}): HydratedAdminSettings {
  const timeline = (value.announcement?.timeline ?? DEFAULT_ADMIN_SETTINGS.announcement.timeline ?? [])
    .map((item) => ({ ...item }));
  const benefits = (value.sections?.benefits ?? DEFAULT_ADMIN_SETTINGS.sections.benefits)
    .map((item) => ({ ...item }));
  const steps = [...(value.sections?.steps ?? DEFAULT_ADMIN_SETTINGS.sections.steps)];
  const faq = (value.sections?.faq ?? DEFAULT_ADMIN_SETTINGS.sections.faq)
    .map((item) => ({ ...item }));

  const settings: PublicSettings = {
    ...DEFAULT_ADMIN_SETTINGS,
    ...value,
    copy: { ...DEFAULT_ADMIN_SETTINGS.copy, ...value.copy },
    links: { ...DEFAULT_ADMIN_SETTINGS.links, ...value.links },
    client: { ...DEFAULT_ADMIN_SETTINGS.client, ...value.client },
    announcement: { ...DEFAULT_ADMIN_SETTINGS.announcement, ...value.announcement, timeline },
    features: { ...DEFAULT_ADMIN_SETTINGS.features, ...value.features },
    operations: { ...DEFAULT_ADMIN_SETTINGS.operations, ...value.operations },
    sections: { ...DEFAULT_ADMIN_SETTINGS.sections, ...value.sections, benefits, steps, faq },
  };

  return {
    settings,
    stepsText: steps.join('\n'),
    faqText: faq.map((item) => `${item.q}|${item.a}`).join('\n'),
    timelineText: timeline.map((item) => `${item.date || ''}|${item.body || ''}`).join('\n'),
  };
}
