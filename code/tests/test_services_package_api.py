import unittest

from app.services import (
    ActorDetailLibrary,
    AutoLoginService,
    CodePrefixDetailLibrary,
    CodePrefixLibrary,
    ComboEnrichmentService,
    LadderBoardService,
    LibraryAdminService,
    LibraryEnrichmentService,
    LocalVideoLibraryService,
    NetworkGuardService,
    VideoFilterService,
    extract_code_prefix,
    split_actor_names,
)
from app.services.auth import AutoLoginService as PackageAutoLoginService
from app.services.detail import ActorDetailLibrary as PackageActorDetailLibrary
from app.services.detail import CodePrefixDetailLibrary as PackageCodePrefixDetailLibrary
from app.services.enrichment import ComboEnrichmentService as PackageComboEnrichmentService
from app.services.enrichment import LibraryEnrichmentService as PackageLibraryEnrichmentService
from app.services.identity import split_actor_names as package_split_actor_names
from app.services.ladder import LadderBoardService as PackageLadderBoardService
from app.services.library import CodePrefixLibrary as PackageCodePrefixLibrary
from app.services.library import LibraryAdminService as PackageLibraryAdminService
from app.services.library import extract_code_prefix as package_extract_code_prefix
from app.services.local_video import LocalVideoLibraryService as PackageLocalVideoLibraryService
from app.services.system import NetworkGuardService as PackageNetworkGuardService
from app.services.video import VideoFilterService as PackageVideoFilterService


class ServicesPackageApiTest(unittest.TestCase):
    def test_top_level_services_exports_match_subpackage_exports(self):
        self.assertIs(ActorDetailLibrary, PackageActorDetailLibrary)
        self.assertIs(AutoLoginService, PackageAutoLoginService)
        self.assertIs(CodePrefixDetailLibrary, PackageCodePrefixDetailLibrary)
        self.assertIs(CodePrefixLibrary, PackageCodePrefixLibrary)
        self.assertIs(ComboEnrichmentService, PackageComboEnrichmentService)
        self.assertIs(LadderBoardService, PackageLadderBoardService)
        self.assertIs(LibraryAdminService, PackageLibraryAdminService)
        self.assertIs(LibraryEnrichmentService, PackageLibraryEnrichmentService)
        self.assertIs(LocalVideoLibraryService, PackageLocalVideoLibraryService)
        self.assertIs(NetworkGuardService, PackageNetworkGuardService)
        self.assertIs(VideoFilterService, PackageVideoFilterService)
        self.assertIs(extract_code_prefix, package_extract_code_prefix)
        self.assertIs(split_actor_names, package_split_actor_names)


if __name__ == '__main__':
    unittest.main()
