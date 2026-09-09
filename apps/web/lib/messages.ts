// Bilingual message catalogs. English is the source of truth and default locale;
// French is opt-in via the language switcher. The child's story language
// (Child.language) is independent of this UI locale.
//
// Values may contain {placeholder} tokens, interpolated by the t() helper.
// Keep the two catalogs structurally identical.

export type Locale = "en" | "fr";

export const LOCALES: Locale[] = ["en", "fr"];
export const DEFAULT_LOCALE: Locale = "en";

const en = {
  navigation: {
    brand: "Story Forge",
    legal: "Legal information",
    privacy: "Privacy",
    terms: "Terms",
  },
  common: {
    back: "← Back",
    backHome: "← Back to home",
    backToChildren: "← Back to children",
    loading: "Loading…",
    loadFailed: "Failed to load. Please try again.",
  },
  langSwitch: {
    en: "EN",
    fr: "FR",
  },
  auth: {
    registerTitle: "Create your account",
    loginTitle: "Log in",
    email: "Email",
    password: "Password",
    confirmPassword: "Confirm password",
    localeLabel: "Interface language",
    submitRegister: "Sign up",
    submitLogin: "Log in",
    registering: "Signing up…",
    loggingIn: "Logging in…",
    noAccount: "Don't have an account?",
    hasAccount: "Already have an account?",
    registerLink: "Sign up",
    loginLink: "Log in",
    passwordMismatch: "Passwords do not match.",
    invalidCredentials: "Invalid email or password.",
    emailExists:
      "An account with this email already exists. Log in with your password or continue with Google.",
    or: "or",
    googleUnavailable: "Google sign-in is temporarily unavailable.",
    googleFailed: "Google sign-in could not be completed. Please try again.",
    googleLinkPrompt:
      "An account with this email already exists. Enter your Story Forge password to link Google securely.",
    googleLinkPassword: "Existing Story Forge password",
    googleLinkSubmit: "Link Google account",
    googleLinking: "Linking…",
    googleConflict: "This email is already linked to another Google account.",
    localeSaveFailed: "Language preference could not be saved.",
    success: "Account created successfully.",
    agreementPrefix: "By creating an account, you agree to our",
    agreementAnd: "and acknowledge our",
    agreementSuffix: ".",
  },
  home: {
    tagline:
      "Turn what happened to your child today into tonight's personalized picture book.",
    loginPrompt: "Log in or create an account to get started.",
    goToChildren: "Go to your children →",
    howItWorks: "How tonight's story comes together",
    shareTitle: "Share the day",
    shareBody: "Tell us one moment, challenge, or small win from your child's day.",
    createTitle: "Create their book",
    createBody: "Story Forge turns it into a personalized illustrated storybook.",
    reviewTitle: "Review before bedtime",
    reviewBody: "You approve every story before it appears in the child reader.",
  },
  children: {
    title: "Your children",
    intro: "Choose a child to create tonight's story, review past books, or manage reader access.",
    upgrade: "Upgrade ({n} free stories left)",
    subscribed: "Subscribed",
    manageSubscription: "Manage subscription",
    portalUnavailable: "Subscription management is unavailable right now.",
    empty: "No child profiles yet.",
    profilesTitle: "Child profiles",
    profileCount: "{n} profiles",
    addProfile: "Add child",
    addFirstProfile: "Add your first child profile",
    addTitle: "Add a child profile",
    addDescription: "Set their details and preferred story language. You can change these later.",
    namePlaceholder: "Name",
    agePlaceholder: "Age",
    interestsLabel: "Interests",
    interestsPlaceholder: "Interests (dinosaurs, unicorns…)",
    storyLanguageLabel: "Story language",
    storyLangFr: "Story language: French",
    storyLangEn: "Story language: English",
    photoLabel: "Reference photo",
    photoHelp:
      "JPEG, PNG, or WebP, up to 10 MB. Used privately to keep the illustrated character consistent.",
    photoChoose: "Choose photo",
    photoReplace: "Replace photo",
    photoRemove: "Remove photo",
    photoSelected: "New photo selected",
    photoUploading: "Uploading photo…",
    photoUploadAfterSave:
      "The profile was saved, but the photo upload failed. Edit the profile to try again.",
    photoRemoveFailed: "Photo removal failed",
    add: "Add",
    edit: "Edit",
    openProfile: "Open profile",
    editProfile: "Edit profile",
    delete: "Delete",
    save: "Save",
    saveChanges: "Save changes",
    cancel: "Cancel",
    noInterests: "no interests",
    yearsOld: "{age} yo",
    langEn: "English",
    langFr: "French",
    saveFailed: "Save failed",
    deleteFailed: "Delete failed",
    deleteChildConfirm:
      "Delete {name}'s profile? All their storybooks will be deleted too.",
    privacy: "Privacy",
    logout: "Log out",
    deleteAccount: "Delete account & all data",
    deleteConfirm1:
      "Deleting your account permanently removes all child profiles, storybooks, and audio. This cannot be undone. Continue?",
    deleteConfirm2:
      "Final confirmation: really delete the entire account?",
    deleteAccountFailed: "Deletion failed",
    deleteAccountSubscriptionCancellationFailed:
      "We could not confirm that your subscription was cancelled, so your account and data were not deleted. Please try again.",
  },
  child: {
    workspaceLabel: "Child workspace",
    tonightTitle: "{name}'s storybook tonight",
    whatHappened: "What happened today?",
    eventHelp: "Share one moment from today. You can review the complete story before your child sees it.",
    freeRemaining: "{n} free stories left",
    eventPlaceholder:
      "wouldn't brush teeth, scared of the dark, argued with a friend…",
    generate: "Generate tonight's book",
    generating: "Generating…",
    generateFailed: "Generation failed",
    safetyReviewUnavailable:
      "Safety review is temporarily unavailable. Please try again later.",
    safetyProviderNotConfigured:
      "Safety review is not configured. Please contact support.",
    generationFailedBody:
      "The illustrations could not be completed. Please try again later.",
    photoRequiredTitle: "Add a reference photo first",
    photoRequiredBody:
      "Character-consistent illustrations require a private reference photo for {name}.",
    managePhoto: "Add or update reference photo",
    limitReached:
      "Free stories used up. Subscribe to keep generating tonight's book for {name}.",
    upgradeContinue: "Subscribe to keep generating",
    pastBooks: "Past storybooks",
    bookCount: "{n} books",
    profileTitle: "Profile details",
    untitled: "Untitled book",
    noBooks: "No storybooks yet.",
    statusPending: "Awaiting parent review",
    statusApproved: "Published",
    statusRejected: "Rejected",
    statusGenerating: "Generating…",
    statusGenerationFailed: "Needs attention",
    readerAccessTitle: "Child reader access",
    readerAccessDescription:
      "Anyone with this link can view approved stories. Resetting it invalidates the previous link.",
    openReader: "Open child reader",
    copyReaderLink: "Copy reader link",
    resetReaderLink: "Reset reader link",
    resetReaderLinkConfirm:
      "Reset this reader link? Anyone using the previous link will lose access.",
  },
  reader: {
    reviewLabel: "Parent review",
    generatingTitle: "Generating story",
    generatingBody:
      "The story, illustrations, and narration are still being prepared.",
    generationFailedTitle: "Story generation failed",
    generationFailedBody:
      "The story could not be completed.",
    retryGeneration: "Retry generation",
    retryingGeneration: "Retrying…",
    editAndRestart: "Edit and start over",
    restartGeneration: "Starting over…",
    recoveryInProgress: "Recovery is in progress.",
    recoveryConflict: "This story is already being handled. Please refresh.",
    recoveryFailed: "The story could not be restarted. Please try again.",
    recoveryAttemptsExhausted:
      "This story could not be completed after several attempts. Start a new story or contact support.",
    startNewStory: "Start a new story",
    stageStoryText: "Writing and checking the story.",
    stageIllustrations: "Creating the illustrations.",
    stageNarration: "Recording the narration.",
    stageComplete: "Finishing the story.",
    narrationComing: "Narration is still being recorded…",
    retryLater:
      "Please return to the child's page and try again later.",
    rejectedTitle: "Rejected",
    rejectedBody: "This story did not pass the safety review.",
    editAndRegenerate:
      "Edit what happened and generate a safer version.",
    eventLabel: "What happened today?",
    regenerate: "Regenerate story",
    regenerating: "Regenerating…",
    regenerateFailed:
      "The story could not be regenerated. Please try again.",
    regenerateLimitReached:
      "Free stories used up. Subscribe before regenerating this story.",
    regeneratePhotoRequired:
      "Add a reference photo before regenerating this story.",
    parentRejected: "This story was rejected during parent review.",
    previewTitle: "Parent preview: {title}",
    pageNumber: "Page {n}",
    pageIllustrationAlt: "Illustration for page {n}",
    reviewPrompt: "Review every page before making this story visible to your child.",
    costNote:
      "Generation cost ≈ ${cost}. The child sees it only after you approve.",
    approve: "Approve & publish to child",
    reject: "Reject",
    reviewFailed: "Couldn't update the review. Please try again.",
    prev: "Previous",
    next: "Next",
  },
  childReader: {
    title: "Storybooks",
    empty: "No stories yet.",
    pageCount: "{n} page",
    pageCountOther: "{n} pages",
    pageOf: "Page {current} of {total}",
    prev: "Previous page",
    next: "Next page",
    notFound: "Story not found.",
    loading: "Loading story…",
  },
  generationErrors: {
    providerNotConfigured:
      "The illustration provider is not configured. Please contact support.",
    referencePhotoUnreadable:
      "The private reference photo could not be read. Please replace it and try again.",
    unavailable:
      "The illustration service is temporarily unavailable. Please try again later.",
    moderated:
      "The illustration provider's safety checks could not approve this image request.",
    requestInvalid:
      "The reference photo or illustration request could not be processed.",
    invalidImage: "The illustration service returned an invalid image.",
    storageFailed:
      "The generated illustration could not be stored.",
    generic:
      "The story could not be completed. Please try again later.",
    storyFailed: "The story text could not be completed. Please try again.",
    illustrationFailed:
      "The illustrations could not be completed. Check the reference photo and try again.",
    narrationFailed: "The narration could not be completed. Please try again.",
    attemptsExhausted:
      "This story could not be completed after several attempts. Start a new story or contact support.",
    storyProviderNotConfigured:
      "The story provider is not configured. Please contact support.",
    narrationProviderNotConfigured:
      "The narration provider is not configured. Please contact support.",
  },
  billing: {
    confirmingTitle: "Confirming your subscription…",
    confirmingBody:
      "Waiting for payment confirmation. This normally takes a few seconds.",
    successTitle: "You're subscribed!",
    successBody: "Unlimited bedtime books, starting tonight.",
    cancelTitle: "Checkout canceled",
    cancelBody:
      "Nothing was charged. You can subscribe any time.",
    backToApp: "Back to the app",
    notConfigured: "Billing is not configured.",
    portalUnavailable: "Billing portal is not available.",
  },
  privacy: {
    metaTitle: "Privacy · Story Forge",
    heading: "Privacy Policy",
    intro:
      "Story Forge generates personalized storybooks for children. This page explains what data the service uses and the choices available to parents.",
    collectHeading: "What we collect",
    collectParent:
      "Parent account information, including email, authentication details, interface language, usage allowance, and subscription identifiers.",
    collectChild:
      "Child profile information: name, age, interests, story language, and an optional reference photo.",
    collectEvent:
      "The daily-event text a parent provides as source material for a story.",
    collectContent:
      "Generated story text, illustrations, narration audio, moderation results, and generation and cost records.",
    collectAnalytics:
      "Redacted page-view information, such as the page category, device type, browser, and approximate location, when Vercel Web Analytics is enabled.",
    purposesHeading: "Why we use it",
    purposes:
      "We use this data to authenticate parents, personalize and review stories, provide illustrations and narration, operate subscriptions, prevent abuse, monitor reliability, and maintain the service.",
    providersHeading: "Configured service providers",
    providersIntro:
      "Depending on deployment settings and the feature used, limited data may be sent to these provider categories. Not every provider receives every request.",
    providersStory:
      "Story generation providers, such as Groq or Anthropic, may receive the child's name, age, interests, story language, page count, and the daily event.",
    providersModeration:
      "The configured moderation provider, such as OpenAI, receives generated titles and pages for safety review—not the original parent event.",
    providersImages:
      "Illustration providers, such as Cloudflare Workers AI or Black Forest Labs, may receive a generated scene prompt and, when configured and supplied, a reference photo.",
    providersNarration:
      "Narration providers, such as DeepInfra, Cloudflare Workers AI, or ElevenLabs, receive generated page text and its language.",
    providersAuthentication:
      "Google receives authentication data only when a parent chooses Google sign-in.",
    providersBilling:
      "Stripe may receive the parent's email, the Story Forge account identifier as a checkout reference, and Stripe customer and subscription identifiers for checkout and subscription management.",
    providersInfrastructure:
      "Hosting and database providers process app requests and stored records; object storage holds managed photos, illustrations, and audio; monitoring receives non-content operational identifiers and failure categories; analytics receives the redacted page-view data described below.",
    readerHeading: "Child reader links",
    readerAccess:
      "After parent approval, a story is available to anyone who has the child's reader link. Treat the link like a password and share it only with people you trust.",
    readerReset:
      "A parent can reset the reader link at any time. Resetting it revokes the previous link without deleting approved stories.",
    readerIndexing:
      "Reader pages are marked not to be indexed or archived by search engines, but this is not an access-control guarantee.",
    retentionHeading: "Retention and deletion",
    retentionRecords:
      "Account, child, event, story, moderation, generation, and account subscription records are generally retained until the parent deletes the relevant child or account.",
    retentionBillingAudit:
      "Stripe webhook audit entries contain event and customer identifiers, an internal account identifier when matched, and timestamps. They are retained separately for deduplication, event ordering, and billing disputes, survive account deletion, and currently have no automatic deletion deadline.",
    retentionAssets:
      "Managed photos, illustrations, and audio enter a durable deletion queue when removed. They may remain until automatic retries succeed or an operator resolves a terminal failure.",
    deletionHeading: "Parent deletion controls",
    deletionControls:
      "Parents can delete a child profile and its related stories and managed assets, or delete the entire account.",
    deletionBilling:
      "Account deletion does not proceed while a known Stripe subscription cannot be confirmed cancelled, preventing deletion from leaving an active subscription behind.",
    analyticsHeading: "Analytics choices",
    analyticsRedaction:
      "Before analytics is sent, Story Forge removes query strings and fragments and replaces child IDs, story IDs, and reader capability tokens in paths with a generic marker.",
    analyticsOptOut:
      "You can block analytics requests with browser privacy controls or a content blocker. Deployments can also disable analytics entirely.",
    controlHeading: "Parent controls",
    control1:
      "Every storybook requires parent preview and approval before the child sees it.",
    control2:
      "You can edit or delete any child profile at any time.",
    contactHeading: "Contact",
    contact:
      "For private questions or requests about your data, email:",
    contactEmail: "privacy@storyforge.invalid",
    contactTemporary:
      "Temporary unmonitored placeholder—replace this address before launch. Do not send personal information to it.",
  },
  terms: {
    metaTitle: "Terms of Service · Story Forge",
    heading: "Terms of Service",
    intro:
      "By using Story Forge you agree to these terms. They may be updated from time to time.",
    contentHeading: "Using the service",
    content1:
      "Story Forge creates personalized AI storybooks from information you provide. You are responsible for the content you enter.",
    content2:
      "Stories require your review and approval before they become visible to children.",
    content3:
      "You may cancel your subscription at any time through the billing portal.",
    changesHeading: "Changes to these terms",
    changes:
      "We may update these terms. Significant changes will be announced on the service.",
    contactHeading: "Contact",
    contact:
      "For questions about these terms, contact the project maintainer.",
  },
  meta: {
    title: "Story Forge — bedtime storybooks",
    description: "Personalized AI bedtime picture books starring your child.",
  },
};

const fr: typeof en = {
  navigation: {
    brand: "Story Forge",
    legal: "Renseignements juridiques",
    privacy: "Confidentialité",
    terms: "Conditions",
  },
  common: {
    back: "← Retour",
    backHome: "← Retour à l'accueil",
    backToChildren: "← Retour aux enfants",
    loading: "Chargement…",
    loadFailed: "Échec du chargement. Veuillez réessayer.",
  },
  langSwitch: {
    en: "EN",
    fr: "FR",
  },
  auth: {
    registerTitle: "Créer votre compte",
    loginTitle: "Se connecter",
    email: "E-mail",
    password: "Mot de passe",
    confirmPassword: "Confirmer le mot de passe",
    localeLabel: "Langue de l'interface",
    submitRegister: "S'inscrire",
    submitLogin: "Se connecter",
    registering: "Inscription…",
    loggingIn: "Connexion…",
    noAccount: "Pas encore de compte ?",
    hasAccount: "Déjà un compte ?",
    registerLink: "S'inscrire",
    loginLink: "Se connecter",
    passwordMismatch: "Les mots de passe ne correspondent pas.",
    invalidCredentials: "E-mail ou mot de passe invalide.",
    emailExists:
      "Un compte avec cet e-mail existe déjà. Connectez-vous avec votre mot de passe ou continuez avec Google.",
    or: "ou",
    googleUnavailable: "La connexion Google est temporairement indisponible.",
    googleFailed:
      "La connexion Google n'a pas pu être effectuée. Veuillez réessayer.",
    googleLinkPrompt:
      "Un compte avec cet e-mail existe déjà. Saisissez votre mot de passe Story Forge pour associer Google en toute sécurité.",
    googleLinkPassword: "Mot de passe Story Forge existant",
    googleLinkSubmit: "Associer le compte Google",
    googleLinking: "Association…",
    googleConflict: "Cet e-mail est déjà associé à un autre compte Google.",
    localeSaveFailed: "La préférence de langue n'a pas pu être enregistrée.",
    success: "Compte créé avec succès.",
    agreementPrefix: "En créant un compte, vous acceptez nos",
    agreementAnd: "et reconnaissez avoir lu notre",
    agreementSuffix: ".",
  },
  home: {
    tagline:
      "Transformez ce qui s'est passé avec votre enfant aujourd'hui en un livre d'images personnalisé pour ce soir.",
    loginPrompt:
      "Connectez-vous ou créez un compte pour commencer.",
    goToChildren: "Aller à vos enfants →",
    howItWorks: "Comment l'histoire de ce soir prend vie",
    shareTitle: "Racontez la journée",
    shareBody: "Partagez un moment, un défi ou une petite victoire de la journée de votre enfant.",
    createTitle: "Créez son livre",
    createBody: "Story Forge le transforme en un livre d'images personnalisé.",
    reviewTitle: "Vérifiez avant le coucher",
    reviewBody: "Vous approuvez chaque histoire avant qu'elle apparaisse dans le lecteur enfant.",
  },
  children: {
    title: "Vos enfants",
    intro: "Choisissez un enfant pour créer l'histoire de ce soir, revoir ses livres ou gérer son accès au lecteur.",
    upgrade: "Passer à Premium ({n} histoires gratuites restantes)",
    subscribed: "Abonné",
    manageSubscription: "Gérer l'abonnement",
    portalUnavailable:
      "La gestion de l'abonnement est indisponible pour le moment.",
    empty: "Aucun profil d'enfant pour le moment.",
    profilesTitle: "Profils d'enfants",
    profileCount: "{n} profils",
    addProfile: "Ajouter un enfant",
    addFirstProfile: "Ajouter votre premier profil d'enfant",
    addTitle: "Ajouter un profil d'enfant",
    addDescription: "Indiquez ses renseignements et la langue de ses histoires. Vous pourrez les modifier plus tard.",
    namePlaceholder: "Nom",
    agePlaceholder: "Âge",
    interestsLabel: "Intérêts",
    interestsPlaceholder: "Intérêts (dinosaures, licornes…)",
    storyLanguageLabel: "Langue de l'histoire",
    storyLangFr: "Langue de l'histoire : Français",
    storyLangEn: "Langue de l'histoire : Anglais",
    photoLabel: "Photo de référence",
    photoHelp:
      "JPEG, PNG ou WebP, max 10 Mo. Utilisée en privé pour maintenir la cohérence du personnage illustré.",
    photoChoose: "Choisir une photo",
    photoReplace: "Remplacer la photo",
    photoRemove: "Supprimer la photo",
    photoSelected: "Nouvelle photo sélectionnée",
    photoUploading: "Téléchargement de la photo…",
    photoUploadAfterSave:
      "Le profil a été enregistré, mais le téléchargement de la photo a échoué. Modifiez le profil pour réessayer.",
    photoRemoveFailed: "Échec de la suppression de la photo",
    add: "Ajouter",
    edit: "Modifier",
    openProfile: "Ouvrir le profil",
    editProfile: "Modifier le profil",
    delete: "Supprimer",
    save: "Enregistrer",
    saveChanges: "Enregistrer les modifications",
    cancel: "Annuler",
    noInterests: "aucun intérêt",
    yearsOld: "{age} ans",
    langEn: "Anglais",
    langFr: "Français",
    saveFailed: "Échec de l'enregistrement",
    deleteFailed: "Échec de la suppression",
    deleteChildConfirm:
      "Supprimer le profil de {name} ? Tous ses livres d'images seront également supprimés.",
    privacy: "Confidentialité",
    logout: "Se déconnecter",
    deleteAccount: "Supprimer le compte et toutes les données",
    deleteConfirm1:
      "La suppression de votre compte supprimera définitivement tous les profils d'enfants, livres et audio. Cette action est irréversible. Continuer ?",
    deleteConfirm2:
      "Confirmation finale : vraiment supprimer le compte entier ?",
    deleteAccountFailed: "Échec de la suppression",
    deleteAccountSubscriptionCancellationFailed:
      "Nous n'avons pas pu confirmer l'annulation de votre abonnement. Votre compte et vos données n'ont donc pas été supprimés. Veuillez réessayer.",
  },
  child: {
    workspaceLabel: "Espace de l'enfant",
    tonightTitle: "Le livre d'images de {name} pour ce soir",
    whatHappened: "Que s'est-il passé aujourd'hui ?",
    eventHelp: "Racontez un moment de la journée. Vous pourrez vérifier toute l'histoire avant que votre enfant la voie.",
    freeRemaining: "{n} histoires gratuites restantes",
    eventPlaceholder:
      "refus de se brosser les dents, a peur du noir, s'est disputé avec un ami…",
    generate: "Générer le livre de ce soir",
    generating: "Génération…",
    generateFailed: "Échec de la génération",
    safetyReviewUnavailable:
      "La revue de sécurité est temporairement indisponible. Veuillez réessayer plus tard.",
    safetyProviderNotConfigured:
      "La revue de sécurité n'est pas configurée. Veuillez contacter le support.",
    generationFailedBody:
      "Les illustrations n'ont pas pu être terminées. Veuillez réessayer plus tard.",
    photoRequiredTitle: "Ajoutez d'abord une photo de référence",
    photoRequiredBody:
      "Les illustrations cohérentes nécessitent une photo de référence privée pour {name}.",
    managePhoto: "Ajouter ou mettre à jour la photo de référence",
    limitReached:
      "Les histoires gratuites sont épuisées. Abonnez-vous pour continuer à générer le livre de {name}.",
    upgradeContinue: "S'abonner pour continuer",
    pastBooks: "Livres précédents",
    bookCount: "{n} livres",
    profileTitle: "Renseignements du profil",
    untitled: "Livre sans titre",
    noBooks: "Aucun livre d'images pour le moment.",
    statusPending: "En attente de validation parentale",
    statusApproved: "Publié",
    statusRejected: "Rejeté",
    statusGenerating: "Génération…",
    statusGenerationFailed: "Action requise",
    readerAccessTitle: "Accès au lecteur enfant",
    readerAccessDescription:
      "Toute personne ayant ce lien peut voir les histoires approuvées. Le réinitialiser invalide le lien précédent.",
    openReader: "Ouvrir le lecteur enfant",
    copyReaderLink: "Copier le lien du lecteur",
    resetReaderLink: "Réinitialiser le lien du lecteur",
    resetReaderLinkConfirm:
      "Réinitialiser ce lien du lecteur ? Toute personne utilisant le lien précédent perdra l'accès.",
  },
  reader: {
    reviewLabel: "Validation parentale",
    generatingTitle: "Génération de l'histoire",
    generatingBody:
      "L'histoire, les illustrations et la narration sont en cours de préparation.",
    generationFailedTitle: "Échec de la génération de l'histoire",
    generationFailedBody:
      "L'histoire n'a pas pu être terminée.",
    retryGeneration: "Réessayer la génération",
    retryingGeneration: "Nouvelle tentative…",
    editAndRestart: "Modifier et recommencer",
    restartGeneration: "Recommencer…",
    recoveryInProgress: "La récupération est en cours.",
    recoveryConflict:
      "Cette histoire est déjà en cours de traitement. Actualisez la page.",
    recoveryFailed:
      "L'histoire n'a pas pu être relancée. Veuillez réessayer.",
    recoveryAttemptsExhausted:
      "Cette histoire n'a pas pu être terminée après plusieurs tentatives. Créez une nouvelle histoire ou contactez le support.",
    startNewStory: "Créer une nouvelle histoire",
    stageStoryText: "Écriture et vérification de l'histoire.",
    stageIllustrations: "Création des illustrations.",
    stageNarration: "Enregistrement de la narration.",
    stageComplete: "Finalisation de l'histoire.",
    narrationComing: "La narration est encore en cours d'enregistrement…",
    retryLater:
      "Veuillez retourner à la page de l'enfant et réessayer plus tard.",
    rejectedTitle: "Rejeté",
    rejectedBody: "Cette histoire n'a pas passé la revue de sécurité.",
    editAndRegenerate:
      "Modifiez ce qui s'est passé et générez une version plus sûre.",
    eventLabel: "Que s'est-il passé aujourd'hui ?",
    regenerate: "Régénérer l'histoire",
    regenerating: "Régénération…",
    regenerateFailed:
      "L'histoire n'a pas pu être régénérée. Veuillez réessayer.",
    regenerateLimitReached:
      "Les histoires gratuites sont épuisées. Abonnez-vous avant de régénérer.",
    regeneratePhotoRequired:
      "Ajoutez une photo de référence avant de régénérer.",
    parentRejected: "Cette histoire a été rejetée lors de la revue parentale.",
    previewTitle: "Aperçu parental : {title}",
    pageNumber: "Page {n}",
    pageIllustrationAlt: "Illustration de la page {n}",
    reviewPrompt: "Vérifiez chaque page avant de rendre cette histoire accessible à votre enfant.",
    costNote:
      "Coût de génération ≈ ${cost}. L'enfant ne le voit qu'après votre approbation.",
    approve: "Approuver et publier pour l'enfant",
    reject: "Rejeter",
    reviewFailed: "Impossible de mettre à jour l'avis. Veuillez réessayer.",
    prev: "Précédent",
    next: "Suivant",
  },
  childReader: {
    title: "Livres d'images",
    empty: "Aucun livre pour le moment.",
    pageCount: "{n} page",
    pageCountOther: "{n} pages",
    pageOf: "Page {current} sur {total}",
    prev: "Page précédente",
    next: "Page suivante",
    notFound: "Histoire introuvable.",
    loading: "Chargement de l'histoire…",
  },
  generationErrors: {
    providerNotConfigured:
      "Le fournisseur d'illustrations n'est pas configuré. Veuillez contacter le support.",
    referencePhotoUnreadable:
      "La photo de référence privée n'a pas pu être lue. Veuillez la remplacer et réessayer.",
    unavailable:
      "Le service d'illustrations est temporairement indisponible. Veuillez réessayer plus tard.",
    moderated:
      "Les contrôles de sécurité du fournisseur n'ont pas pu approuver cette requête.",
    requestInvalid:
      "La photo de référence ou la requête d'illustration n'a pas pu être traitée.",
    invalidImage:
      "Le service d'illustrations a retourné une image invalide.",
    storageFailed:
      "L'illustration générée n'a pas pu être stockée.",
    generic:
      "L'histoire n'a pas pu être terminée. Veuillez réessayer plus tard.",
    storyFailed: "Le texte de l'histoire n'a pas pu être créé. Veuillez réessayer.",
    illustrationFailed:
      "Les illustrations n'ont pas pu être terminées. Vérifiez la photo de référence et réessayez.",
    narrationFailed: "La narration n'a pas pu être créée. Veuillez réessayer.",
    attemptsExhausted:
      "Cette histoire n'a pas pu être terminée après plusieurs tentatives. Créez une nouvelle histoire ou contactez le support.",
    storyProviderNotConfigured:
      "Le fournisseur d'histoires n'est pas configuré. Contactez le support.",
    narrationProviderNotConfigured:
      "Le fournisseur de narration n'est pas configuré. Contactez le support.",
  },
  billing: {
    confirmingTitle: "Confirmation de votre abonnement…",
    confirmingBody:
      "En attente de la confirmation de paiement. Cela prend généralement quelques secondes.",
    successTitle: "Vous êtes abonné !",
    successBody: "Livres pour le soir illimités, à partir de ce soir.",
    cancelTitle: "Paiement annulé",
    cancelBody:
      "Aucun frais n'a été facturé. Vous pouvez vous abonner à tout moment.",
    backToApp: "Retour à l'application",
    notConfigured: "La facturation n'est pas configurée.",
    portalUnavailable: "Le portail de facturation n'est pas disponible.",
  },
  privacy: {
    metaTitle: "Confidentialité · Story Forge",
    heading: "Politique de confidentialité",
    intro:
      "Story Forge génère des livres d'images personnalisés pour les enfants. Cette page explique quelles données le service utilise et les choix offerts aux parents.",
    collectHeading: "Ce que nous collectons",
    collectParent:
      "Les renseignements du compte parent, notamment l'adresse e-mail, les données d'authentification, la langue de l'interface, le quota d'utilisation et les identifiants d'abonnement.",
    collectChild:
      "Les renseignements du profil de l'enfant : nom, âge, intérêts, langue de l'histoire et photo de référence facultative.",
    collectEvent:
      "Le texte sur l'événement de la journée fourni par un parent comme point de départ de l'histoire.",
    collectContent:
      "Le texte, les illustrations et l'audio générés, ainsi que les résultats de modération et les données de génération et de coût.",
    collectAnalytics:
      "Des renseignements expurgés sur les pages consultées, comme la catégorie de page, le type d'appareil, le navigateur et la localisation approximative, lorsque Vercel Web Analytics est activé.",
    purposesHeading: "Pourquoi nous les utilisons",
    purposes:
      "Nous utilisons ces données pour authentifier les parents, personnaliser et réviser les histoires, fournir les illustrations et la narration, gérer les abonnements, prévenir les abus, surveiller la fiabilité et maintenir le service.",
    providersHeading: "Fournisseurs de services configurés",
    providersIntro:
      "Selon la configuration du déploiement et la fonctionnalité utilisée, des données limitées peuvent être transmises à ces catégories de fournisseurs. Chaque fournisseur ne reçoit pas chaque requête.",
    providersStory:
      "Les fournisseurs de génération d'histoires, comme Groq ou Anthropic, peuvent recevoir le nom, l'âge, les intérêts et la langue de l'enfant, le nombre de pages et l'événement de la journée.",
    providersModeration:
      "Le fournisseur de modération configuré, comme OpenAI, reçoit les titres et les pages générés pour l'examen de sécurité, mais pas l'événement original du parent.",
    providersImages:
      "Les fournisseurs d'illustrations, comme Cloudflare Workers AI ou Black Forest Labs, peuvent recevoir une description de scène générée et, lorsqu'elle est configurée et fournie, une photo de référence.",
    providersNarration:
      "Les fournisseurs de narration, comme DeepInfra, Cloudflare Workers AI ou ElevenLabs, reçoivent le texte généré de la page et sa langue.",
    providersAuthentication:
      "Google reçoit des données d'authentification uniquement lorsqu'un parent choisit la connexion avec Google.",
    providersBilling:
      "Stripe peut recevoir l'adresse e-mail du parent, l'identifiant du compte Story Forge comme référence de paiement, ainsi que les identifiants Stripe du client et de l'abonnement pour le paiement et la gestion de l'abonnement.",
    providersInfrastructure:
      "Les fournisseurs d'hébergement et de base de données traitent les requêtes et les données enregistrées; le stockage d'objets contient les photos, illustrations et fichiers audio gérés; la surveillance reçoit des identifiants opérationnels sans contenu et des catégories d'échec; l'analytique reçoit les données expurgées décrites ci-dessous.",
    readerHeading: "Liens de lecture pour l'enfant",
    readerAccess:
      "Après l'approbation parentale, une histoire est accessible à toute personne possédant le lien de lecture de l'enfant. Traitez ce lien comme un mot de passe et partagez-le uniquement avec des personnes de confiance.",
    readerReset:
      "Un parent peut réinitialiser le lien de lecture à tout moment. La réinitialisation révoque l'ancien lien sans supprimer les histoires approuvées.",
    readerIndexing:
      "Les pages de lecture indiquent aux moteurs de recherche de ne pas les indexer ni les archiver, mais cela ne garantit pas le contrôle d'accès.",
    retentionHeading: "Conservation et suppression",
    retentionRecords:
      "Les données du compte, de l'enfant, des événements, des histoires, de la modération, de la génération et de l'abonnement du compte sont généralement conservées jusqu'à ce que le parent supprime l'enfant concerné ou le compte.",
    retentionBillingAudit:
      "Les entrées d'audit des webhooks Stripe contiennent des identifiants d'événement et de client, un identifiant de compte interne lorsqu'il est associé, et des horodatages. Elles sont conservées séparément pour la déduplication, l'ordre des événements et les litiges de facturation, subsistent après la suppression du compte et n'ont actuellement aucun délai de suppression automatique.",
    retentionAssets:
      "Les photos, illustrations et fichiers audio gérés sont placés dans une file de suppression durable lorsqu'ils sont retirés. Ils peuvent subsister jusqu'à la réussite des nouvelles tentatives automatiques ou la résolution d'un échec terminal par un opérateur.",
    deletionHeading: "Contrôles de suppression parentaux",
    deletionControls:
      "Les parents peuvent supprimer le profil d'un enfant, ses histoires et ses ressources gérées, ou supprimer le compte entier.",
    deletionBilling:
      "La suppression du compte ne se poursuit pas lorsqu'il est impossible de confirmer l'annulation d'un abonnement Stripe connu, afin de ne pas laisser un abonnement actif après la suppression.",
    analyticsHeading: "Choix relatifs à l'analytique",
    analyticsRedaction:
      "Avant l'envoi des données analytiques, Story Forge retire les chaînes de requête et les fragments, puis remplace les identifiants d'enfant et d'histoire et les jetons d'accès aux liens de lecture par un marqueur générique.",
    analyticsOptOut:
      "Vous pouvez bloquer les requêtes analytiques avec les réglages de confidentialité du navigateur ou un bloqueur de contenu. Le déploiement peut également désactiver complètement l'analytique.",
    controlHeading: "Contrôles parentaux",
    control1:
      "Chaque livre nécessite une prévisualisation et une approbation parentale avant que l'enfant ne le voie.",
    control2:
      "Vous pouvez modifier ou supprimer un profil d'enfant à tout moment.",
    contactHeading: "Contact",
    contact:
      "Pour des questions ou des demandes privées concernant vos données, écrivez à :",
    contactEmail: "privacy@storyforge.invalid",
    contactTemporary:
      "Adresse temporaire non surveillée — remplacez-la avant le lancement. N'y envoyez aucun renseignement personnel.",
  },
  terms: {
    metaTitle: "Conditions d'utilisation · Story Forge",
    heading: "Conditions d'utilisation",
    intro:
      "En utilisant Story Forge, vous acceptez ces conditions. Elles peuvent être mises à jour de temps en temps.",
    contentHeading: "Utilisation du service",
    content1:
      "Story Forge crée des livres d'images personnalisés à partir des informations que vous fournissez. Vous êtes responsable du contenu que vous saisissez.",
    content2:
      "Les histoires nécessitent votre examen et votre approbation avant de devenir visibles pour les enfants.",
    content3:
      "Vous pouvez annuler votre abonnement à tout moment via le portail de facturation.",
    changesHeading: "Modifications de ces conditions",
    changes:
      "Nous pouvons modifier ces conditions. Les changements importants seront annoncés sur le service.",
    contactHeading: "Contact",
    contact:
      "Pour des questions sur ces conditions, contactez le mainteneur du projet.",
  },
  meta: {
    title: "Story Forge — livres d'images pour le soir",
    description:
      "Livres d'images IA personnalisés mettant en scène votre enfant.",
  },
};

export const messages = { en, fr };
