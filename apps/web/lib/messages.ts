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
  common: {
    back: "← Back",
    backToChildren: "← Back to children",
    loading: "Loading…",
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
    emailExists: "An account with this email already exists.",
    success: "Account created successfully.",
  },
  home: {
    tagline:
      "Turn what happened to your child today into tonight's personalized picture book.",
    loginPrompt: "Log in or create an account to get started.",
    goToChildren: "Go to your children →",
  },
  children: {
    title: "Your children",
    upgrade: "Upgrade ({n} free stories left)",
    subscribed: "Subscribed",
    manageSubscription: "Manage subscription",
    portalUnavailable: "Subscription management is unavailable right now.",
    empty: "No child profiles yet.",
    addTitle: "Add a child profile",
    namePlaceholder: "Name",
    agePlaceholder: "Age",
    interestsPlaceholder: "Interests (dinosaurs, unicorns…)",
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
    delete: "Delete",
    save: "Save",
    cancel: "Cancel",
    noInterests: "no interests",
    yearsOld: "{age} yo",
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
  },
  child: {
    tonightTitle: "{name}'s storybook tonight",
    whatHappened: "What happened today?",
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
    untitled: "Untitled book",
    noBooks: "No storybooks yet.",
    statusPending: "Awaiting parent review",
    statusApproved: "Published",
    statusRejected: "Rejected",
    statusGenerating: "Generating…",
    statusGenerationFailed: "Generation failed",
  },
  reader: {
    generatingTitle: "Generating illustrations",
    generatingBody:
      "The story text is ready and its illustrations are still being generated.",
    generationFailedTitle: "Illustration generation failed",
    generationFailedBody:
      "The story text was saved, but the illustrations could not be completed.",
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
    costNote:
      "Generation cost ≈ ${cost}. The child sees it only after you approve.",
    approve: "Approve & publish to child",
    reject: "Reject",
    prev: "Previous",
    next: "Next",
  },
  childReader: {
    title: "{name}'s storybooks",
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
    narrationFailed:
      "Narration generation failed. Please try again later.",
    generic:
      "The story could not be completed. Please try again later.",
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
  },
  privacy: {
    metaTitle: "Privacy · Story Forge",
    heading: "Privacy Policy",
    intro:
      "Story Forge generates personalized storybooks for children. Your child's data belongs to you.",
    collectHeading: "What we collect",
    collectParent: "Email (for login and subscription management).",
    collectChild:
      "Name, age, interests, story language, and an optional reference photo — used only to generate age-appropriate stories starring your child.",
    collectEvent:
      "What you type about the day, used only as material for story generation.",
    collectContent:
      "Story text, illustrations, and narration audio, for you and your child to revisit.",
    controlHeading: "Parent controls",
    control1:
      "Every storybook requires parent preview and approval before the child sees it.",
    control2:
      "You can edit or delete any child profile at any time.",
    contactHeading: "Contact",
    contact:
      "For questions about your data, contact the project maintainer.",
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
  common: {
    back: "← Retour",
    backToChildren: "← Retour aux enfants",
    loading: "Chargement…",
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
    emailExists: "Un compte avec cet e-mail existe déjà.",
    success: "Compte créé avec succès.",
  },
  home: {
    tagline:
      "Transformez ce qui s'est passé avec votre enfant aujourd'hui en un livre d'images personnalisé pour ce soir.",
    loginPrompt:
      "Connectez-vous ou créez un compte pour commencer.",
    goToChildren: "Aller à vos enfants →",
  },
  children: {
    title: "Vos enfants",
    upgrade: "Passer à Premium ({n} histoires gratuites restantes)",
    subscribed: "Abonné",
    manageSubscription: "Gérer l'abonnement",
    portalUnavailable:
      "La gestion de l'abonnement est indisponible pour le moment.",
    empty: "Aucun profil d'enfant pour le moment.",
    addTitle: "Ajouter un profil d'enfant",
    namePlaceholder: "Nom",
    agePlaceholder: "Âge",
    interestsPlaceholder: "Intérêts (dinosaures, licornes…)",
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
    delete: "Supprimer",
    save: "Enregistrer",
    cancel: "Annuler",
    noInterests: "aucun intérêt",
    yearsOld: "{age} ans",
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
  },
  child: {
    tonightTitle: "Le livre d'images de {name} pour ce soir",
    whatHappened: "Que s'est-il passé aujourd'hui ?",
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
    untitled: "Livre sans titre",
    noBooks: "Aucun livre d'images pour le moment.",
    statusPending: "En attente de validation parentale",
    statusApproved: "Publié",
    statusRejected: "Rejeté",
    statusGenerating: "Génération…",
    statusGenerationFailed: "Échec de la génération",
  },
  reader: {
    generatingTitle: "Génération des illustrations",
    generatingBody:
      "Le texte de l'histoire est prêt, les illustrations sont en cours de génération.",
    generationFailedTitle: "Échec de la génération d'illustrations",
    generationFailedBody:
      "Le texte a été enregistré, mais les illustrations n'ont pas pu être terminées.",
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
    costNote:
      "Coût de génération ≈ ${cost}. L'enfant ne le voit qu'après votre approbation.",
    approve: "Approuver et publier pour l'enfant",
    reject: "Rejeter",
    prev: "Précédent",
    next: "Suivant",
  },
  childReader: {
    title: "Les livres d'images de {name}",
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
    narrationFailed:
      "La génération de narration a échoué. Veuillez réessayer plus tard.",
    generic:
      "L'histoire n'a pas pu être terminée. Veuillez réessayer plus tard.",
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
  },
  privacy: {
    metaTitle: "Confidentialité · Story Forge",
    heading: "Politique de confidentialité",
    intro:
      "Story Forge génère des livres d'images personnalisés pour les enfants. Les données de votre enfant vous appartiennent.",
    collectHeading: "Ce que nous collectons",
    collectParent:
      "E-mail (pour la connexion et la gestion de l'abonnement).",
    collectChild:
      "Nom, âge, intérêts, langue de l'histoire et photo de référence optionnelle — uniquement pour générer des histoires adaptées à l'âge.",
    collectEvent:
      "Ce que vous écrivez sur la journée, utilisé uniquement comme matière pour la génération.",
    collectContent:
      "Texte de l'histoire, illustrations et audio de narration, pour que vous et votre enfant puissiez les revisiter.",
    controlHeading: "Contrôles parentaux",
    control1:
      "Chaque livre nécessite une prévisualisation et une approbation parentale avant que l'enfant ne le voie.",
    control2:
      "Vous pouvez modifier ou supprimer un profil d'enfant à tout moment.",
    contactHeading: "Contact",
    contact:
      "Pour des questions sur vos données, contactez le mainteneur du projet.",
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
